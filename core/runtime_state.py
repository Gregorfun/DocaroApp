from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RuntimeStateConfig:
    repo_root: Path
    data_dir: Path
    runtime_dirs: tuple[Path, ...]
    runtime_files: tuple[Path, ...]
    log_dir: Path
    preserve_dirs: tuple[Path, ...] = ()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _is_preserved(path: Path, preserve_dirs: Iterable[Path]) -> bool:
    for p in preserve_dirs:
        if _is_within(path, p):
            return True
    return False


def _clear_directory_contents(dir_path: Path, preserve_dirs: Iterable[Path]) -> None:
    if not dir_path.exists() or not dir_path.is_dir():
        return
    for child in dir_path.iterdir():
        if _is_preserved(child, preserve_dirs):
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            # Best-effort cleanup
            pass


def _delete_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def reset_runtime_state(cfg: RuntimeStateConfig) -> None:
    """Reset all non-ML runtime state so Docaro becomes stateless.

    This function is intentionally best-effort: failures should not prevent startup.
    """

    preserve = tuple(Path(p) for p in cfg.preserve_dirs)

    for f in cfg.runtime_files:
        if _is_preserved(f, preserve):
            continue
        _delete_file(f)

    for d in cfg.runtime_dirs:
        if _is_preserved(d, preserve):
            continue
        d.mkdir(parents=True, exist_ok=True)
        _clear_directory_contents(d, preserve)

    # Logs: clear file contents, keep directory
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory_contents(cfg.log_dir, preserve)


def reset_runtime_state_once(cfg: RuntimeStateConfig, marker_path: Path | None = None) -> bool:
    """Reset runtime state at most once per systemd service invocation.

    Gunicorn with multiple workers (and worker restarts) imports the app module
    in each worker process. Calling :func:`reset_runtime_state` unconditionally
    from module import time can therefore erase in-flight uploads or recently
    processed outputs whenever a worker restarts.

    This helper uses systemd's ``INVOCATION_ID`` (when available) to ensure the
    reset happens only once per service start.

    Returns:
        True if a reset was performed, False if skipped.
    """

    invocation_id = (os.getenv("INVOCATION_ID") or "").strip()
    if marker_path is None:
        marker_path = cfg.data_dir / ".runtime_reset_invocation"

    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        if marker_path.exists():
            existing = marker_path.read_text(encoding="utf-8").strip()
            if invocation_id:
                if existing.startswith(invocation_id):
                    return False
            else:
                # Fallback: if no systemd invocation id is available,
                # only reset once per marker file presence.
                return False
    except Exception:
        # Best-effort: if we can't read the marker, continue and reset.
        pass

    reset_runtime_state(cfg)

    try:
        stamp = f"{invocation_id}\n{int(time.time())}\n"
        tmp_path = marker_path.with_suffix(".tmp")
        tmp_path.write_text(stamp, encoding="utf-8")
        tmp_path.replace(marker_path)
    except Exception:
        pass

    return True
