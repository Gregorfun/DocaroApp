from __future__ import annotations

from pathlib import Path

from app.queue_runtime import QueueRuntimeManager


class _BrokenQueue:
    @property
    def count(self):
        raise RuntimeError("redis offline")


def test_evaluate_inbox_request_tolerates_queue_depth_error(tmp_path: Path):
    inbox_dir = tmp_path / "eingang"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    (inbox_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")

    recorded_errors: list[str] = []
    progress_calls: list[tuple[int, int, str]] = []

    manager = QueueRuntimeManager(
        q=_BrokenQueue(),
        queue_max_depth=200,
        default_inbox_dir=inbox_dir,
        out_dir=tmp_path / "fertig",
        quarantine_dir=tmp_path / "quarantaene",
        resolve_inbox_dir_for_scope=lambda user_scope: inbox_dir,
        resolve_out_dir=lambda user_scope: tmp_path / "fertig",
        resolve_quarantine_dir=lambda user_scope: tmp_path / "quarantaene",
        refresh_runtime_metrics=lambda: None,
        is_processing=lambda user_scope="": False,
        set_progress=lambda total, done, current_file, job_id="", user_scope="": progress_calls.append(
            (total, done, current_file)
        ),
        set_processing=lambda value, user_scope="": None,
        get_auto_sort_settings=lambda: type("Settings", (), {"inbox_dir": inbox_dir})(),
        resolve_inbox_dir=lambda path: Path(path),
        looks_like_windows_drive_path=lambda value: False,
        windows_path_not_supported_message=lambda value: value,
        normalize_date_fmt=lambda raw: raw or "%Y-%m-%d",
        process_folder=lambda *args, **kwargs: [],
        clear_pdfs=lambda path: None,
        apply_result_flags=lambda results: results,
        apply_quarantine=lambda results, user_scope="": results,
        merge_last_results=lambda results, user_scope="": None,
        clear_progress=lambda user_scope="": None,
        processing_flag_path=lambda user_scope="": tmp_path / "processing.flag",
        get_unique_path=lambda path, name: Path(path) / name,
        observe_pipeline_step=lambda name, duration: None,
        set_inflight=lambda name, value: None,
        count_step_error=lambda name, exc: recorded_errors.append(name),
        log_exception=lambda context, exc: None,
    )

    decision = manager.evaluate_inbox_request("%d.%m.%Y", user_scope="user_1")

    assert decision.proceed is True
    assert decision.inbox_dir == inbox_dir
    assert progress_calls == [(1, 0, "")]
    assert "queue_depth" in recorded_errors