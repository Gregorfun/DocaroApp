from __future__ import annotations

import shutil
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
