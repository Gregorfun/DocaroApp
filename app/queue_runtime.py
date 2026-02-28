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
        resolve_inbox_dir_for_scope: Callable[[str], Path],
        resolve_out_dir: Callable[[str], Path],
        resolve_quarantine_dir: Callable[[str], Path],
        refresh_runtime_metrics: Callable[[], None],
        is_processing: Callable[[], bool],
        set_progress: Callable[..., None],
        set_processing: Callable[..., None],
        get_auto_sort_settings: Callable,
        resolve_inbox_dir: Callable[[Path], Path],
        looks_like_windows_drive_path: Callable[[str], bool],
        windows_path_not_supported_message: Callable[[str], str],
        normalize_date_fmt: Callable[[str], str],
        process_folder: Callable,
        clear_pdfs: Callable[[Path], None],
        apply_result_flags: Callable,
        apply_quarantine: Callable,
        merge_last_results: Callable[..., None],
        clear_progress: Callable[..., None],
        processing_flag_path: Callable[[str], Path],
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
        self.resolve_inbox_dir_for_scope = resolve_inbox_dir_for_scope
        self.resolve_out_dir = resolve_out_dir
        self.resolve_quarantine_dir = resolve_quarantine_dir

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

    def evaluate_inbox_request(self, date_fmt_raw: str, user_scope: str = "") -> InboxDecision:
        self.refresh_runtime_metrics()

        if self.is_processing(user_scope):
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
        default_inbox = self.resolve_inbox_dir_for_scope(user_scope) if user_scope else self.default_inbox_dir
        inbox_dir_raw = getattr(settings, "inbox_dir", default_inbox)
        # Enforce per-user inbox isolation unless an explicit user-local path is configured.
        if user_scope:
            inbox_dir_raw = default_inbox
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
        self.set_progress(total=len(pdfs), done=0, current_file="", job_id="", user_scope=user_scope)
        self.set_processing(True, user_scope=user_scope)
        return InboxDecision(True, inbox_dir=inbox_dir, date_fmt=date_fmt)

    def background_process_folder(
        self,
        input_dir: Path,
        date_fmt: str,
        cleanup_input_dir: bool,
        log_context: str,
        user_scope: str = "",
    ) -> None:
        started = time.perf_counter()
        self.set_inflight("worker_processing", 1)
        out_dir = self.resolve_out_dir(user_scope) if user_scope else self.out_dir
        quarantine_dir = self.resolve_quarantine_dir(user_scope) if user_scope else self.quarantine_dir
        try:
            def _progress_cb(done: int, total: int, filename: str) -> None:
                self.set_progress(total=total, done=done, current_file=filename, user_scope=user_scope)

            results = self.process_folder(input_dir, out_dir, date_format=date_fmt, progress_callback=_progress_cb)

            if results:
                try:
                    quarantine_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    quarantine_dir

                for item in results:
                    if not item.get("parsing_failed") and not item.get("error"):
                        continue
                    original = (item.get("original") or item.get("out_name") or "").strip()
                    if not original:
                        continue
                    src = input_dir / original
                    if not src.exists():
                        continue
                    target = self.get_unique_path(quarantine_dir, src.name)
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
            self.merge_last_results(results, user_scope=user_scope)
        except Exception as exc:
            self.count_step_error("background_process_folder", exc)
            self.log_exception(log_context, exc)
        finally:
            self.observe_pipeline_step("background_process_folder", time.perf_counter() - started)
            self.set_inflight("worker_processing", 0)
            try:
                flag = self.processing_flag_path(user_scope)
                if flag.exists():
                    flag.unlink()
            except OSError:
                pass
            self.clear_progress(user_scope=user_scope)
