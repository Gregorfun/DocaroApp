from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class InboxDecision:
    proceed: bool
    flash_message: str = ""
    inbox_dir: Path | None = None
    date_fmt: str = ""


class QueueRuntimeManager:
    """Queue/inbox orchestration extracted from app/app.py (risk-averse wrapper style)."""

    def __init__(
        self,
        *,
        q,
        queue_max_depth: int,
        default_inbox_dir: Path,
        out_dir: Path,
        quarantine_dir: Path,
        refresh_runtime_metrics: Callable[[], None],
        is_processing: Callable[[], bool],
        set_progress: Callable[[int, int, str], None],
        set_processing: Callable[[bool], None],
        get_auto_sort_settings: Callable,
        resolve_inbox_dir: Callable[[Path], Path],
        looks_like_windows_drive_path: Callable[[str], bool],
        windows_path_not_supported_message: Callable[[str], str],
        normalize_date_fmt: Callable[[str], str],
        process_folder: Callable,
        clear_pdfs: Callable[[Path], None],
        apply_result_flags: Callable,
        apply_quarantine: Callable,
        merge_last_results: Callable,
        clear_progress: Callable[[], None],
        processing_flag_path: Callable[[], Path],
        get_unique_path: Callable,
        observe_pipeline_step: Callable[[str, float], None],
        set_inflight: Callable[[str, int], None],
        count_step_error: Callable[[str, object], None],
        log_exception: Callable[[str, Exception], None],
    ) -> None:
        self.q = q
        self.queue_max_depth = int(queue_max_depth)
        self.default_inbox_dir = default_inbox_dir
        self.out_dir = out_dir
        self.quarantine_dir = quarantine_dir

        self.refresh_runtime_metrics = refresh_runtime_metrics
        self.is_processing = is_processing
        self.set_progress = set_progress
        self.set_processing = set_processing
        self.get_auto_sort_settings = get_auto_sort_settings
        self.resolve_inbox_dir = resolve_inbox_dir
        self.looks_like_windows_drive_path = looks_like_windows_drive_path
        self.windows_path_not_supported_message = windows_path_not_supported_message
        self.normalize_date_fmt = normalize_date_fmt
        self.process_folder = process_folder
        self.clear_pdfs = clear_pdfs
        self.apply_result_flags = apply_result_flags
        self.apply_quarantine = apply_quarantine
        self.merge_last_results = merge_last_results
        self.clear_progress = clear_progress
        self.processing_flag_path = processing_flag_path
        self.get_unique_path = get_unique_path
        self.observe_pipeline_step = observe_pipeline_step
        self.set_inflight = set_inflight
        self.count_step_error = count_step_error
        self.log_exception = log_exception

    def evaluate_inbox_request(self, date_fmt_raw: str) -> InboxDecision:
        self.refresh_runtime_metrics()

        if self.is_processing():
            return InboxDecision(False, "Es läuft bereits eine Verarbeitung.")

        if int(self.q.count) >= self.queue_max_depth:
            return InboxDecision(
                False,
                (
                    f"Queue ist ausgelastet ({int(self.q.count)} Jobs >= Limit {self.queue_max_depth}). "
                    "Bitte später erneut versuchen."
                ),
            )

        settings = self.get_auto_sort_settings()
        inbox_dir_raw = getattr(settings, "inbox_dir", self.default_inbox_dir)
        inbox_dir_raw_str = str(inbox_dir_raw)
        if os.name != "nt" and self.looks_like_windows_drive_path(inbox_dir_raw_str):
            return InboxDecision(False, self.windows_path_not_supported_message(inbox_dir_raw_str))

        inbox_dir = self.resolve_inbox_dir(inbox_dir_raw)
        inbox_dir.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(
            p
            for p in inbox_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"
        )
        if not pdfs:
            return InboxDecision(False, f"Keine PDFs in {inbox_dir} gefunden.")

        date_fmt = self.normalize_date_fmt(date_fmt_raw)
        self.set_progress(total=len(pdfs), done=0)
        self.set_processing(True)
        return InboxDecision(True, inbox_dir=inbox_dir, date_fmt=date_fmt)

    def background_process_folder(
        self,
        input_dir: Path,
        date_fmt: str,
        cleanup_input_dir: bool,
        log_context: str,
    ) -> None:
        started = time.perf_counter()
        self.set_inflight("worker_processing", 1)
        try:
            def _progress_cb(done: int, total: int, filename: str) -> None:
                self.set_progress(total=total, done=done, current_file=filename)

            results = self.process_folder(input_dir, self.out_dir, date_format=date_fmt, progress_callback=_progress_cb)

            if results:
                try:
                    self.quarantine_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    self.quarantine_dir

                for item in results:
                    if not item.get("parsing_failed") and not item.get("error"):
                        continue
                    original = (item.get("original") or item.get("out_name") or "").strip()
                    if not original:
                        continue
                    src = input_dir / original
                    if not src.exists():
                        continue
                    target = self.get_unique_path(self.quarantine_dir, src.name)
                    try:
                        src.replace(target)
                    except OSError:
                        try:
                            shutil.copy2(src, target)
                            try:
                                src.unlink()
                            except OSError:
                                pass
                        except OSError:
                            continue
                    item["out_name"] = target.name
                    item["export_path"] = str(target)
                    item["quarantined"] = "1"
                    item["quarantine_reason"] = "processing_failed"

            if cleanup_input_dir:
                self.clear_pdfs(input_dir)

            results = self.apply_result_flags(results)
            results = self.apply_quarantine(results)
            self.merge_last_results(results)
        except Exception as exc:
            self.count_step_error("background_process_folder", exc)
            self.log_exception(log_context, exc)
        finally:
            self.observe_pipeline_step("background_process_folder", time.perf_counter() - started)
            self.set_inflight("worker_processing", 0)
            try:
                flag = self.processing_flag_path()
                if flag.exists():
                    flag.unlink()
            except OSError:
                pass
            self.clear_progress()
