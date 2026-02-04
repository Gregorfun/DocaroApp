#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import ctypes
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    name: str
    detail: str = ""
    hint: str = ""


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or ""), (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


def _check_cmd(name: str, candidates: Iterable[str] | None = None) -> CheckResult:
    candidates = list(candidates or [name])
    for cand in candidates:
        path = shutil.which(cand)
        if path:
            return CheckResult(True, f"cmd:{name}", detail=path)
    return CheckResult(
        False,
        f"cmd:{name}",
        detail="not found",
        hint=f"Install system package providing {name} (Debian/Ubuntu: apt install ...)",
    )


def _check_import(module_name: str, pip_name: str | None = None) -> CheckResult:
    try:
        __import__(module_name)
        return CheckResult(True, f"py:{module_name}")
    except Exception as exc:
        pkg = pip_name or module_name
        return CheckResult(
            False,
            f"py:{module_name}",
            detail=str(exc),
            hint=f"Install python package: pip install {pkg}",
        )


def _check_module_spec(module_name: str, pip_name: str | None = None) -> CheckResult:
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            pkg = pip_name or module_name
            return CheckResult(
                False,
                f"py:{module_name}",
                detail="not installed",
                hint=f"Install python package: pip install {pkg}",
            )
        return CheckResult(True, f"py:{module_name}")
    except Exception as exc:
        pkg = pip_name or module_name
        return CheckResult(
            False,
            f"py:{module_name}",
            detail=str(exc),
            hint=f"Install python package: pip install {pkg}",
        )


def _check_shared_lib(soname: str, hint: str) -> CheckResult:
    try:
        ctypes.CDLL(soname)
        return CheckResult(True, f"so:{soname}")
    except OSError as exc:
        return CheckResult(False, f"so:{soname}", detail=str(exc), hint=hint)


def _check_writeable_dir(path: Path) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / f"._write_test_{os.getpid()}"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return CheckResult(True, f"fs:{path}")
    except Exception as exc:
        return CheckResult(
            False,
            f"fs:{path}",
            detail=str(exc),
            hint="Ensure service user can write to this directory",
        )


def _check_tesseract_lang(lang: str = "deu") -> CheckResult:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return CheckResult(False, "tesseract:langs", detail="tesseract not found")
    rc, out, err = _run([tesseract, "--list-langs"], timeout=15)
    if rc != 0:
        return CheckResult(False, "tesseract:langs", detail=(err or out).strip())
    langs = {
        ln.strip()
        for ln in (out or "").splitlines()
        if ln.strip() and not ln.lower().startswith("list of")
    }
    if lang in langs:
        return CheckResult(True, "tesseract:langs", detail=f"has {lang}")
    return CheckResult(
        False,
        "tesseract:langs",
        detail=f"missing {lang}. available={sorted(langs)}",
        hint=f"Install language pack: tesseract-ocr-{lang}",
    )


def _pip_install_requirements(requirements_path: Path) -> CheckResult:
    # Always use the current interpreter's pip to avoid mixing system pip
    # with the service venv.
    rc, out, err = _run([sys.executable, "-m", "pip", "--version"], timeout=15)
    if rc != 0:
        return CheckResult(False, "pip:install", detail=(err or out).strip() or "pip not available")

    cmd: list[str] = [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)]
    rc, out, err = _run(cmd, timeout=int(os.getenv("DOCARO_PIP_TIMEOUT", "300")))
    if rc == 0:
        return CheckResult(True, "pip:install", detail="installed requirements")
    return CheckResult(False, "pip:install", detail=(err or out).strip())


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    data_dir = base_dir / "data"

    checks: list[CheckResult] = []
    required_py: list[CheckResult] = []
    optional_py: list[CheckResult] = []

    # Minimal runtime deps (must pass)
    required_py.extend(
        [
            _check_import("flask", "flask"),
            _check_import("argon2", "argon2-cffi"),
            _check_import("pdf2image", "pdf2image"),
            _check_import("pytesseract", "pytesseract"),
            _check_import("PIL", "pillow"),
            _check_import("dateutil", "python-dateutil"),
            _check_import("PyPDF2", "PyPDF2"),
            _check_import("pdfplumber", "pdfplumber"),
            _check_import("yaml", "PyYAML"),
        ]
    )

    # Optional deps (must never block startup)
    optional_py.append(_check_import("fitz", "pymupdf"))
    if os.getenv("DOCARO_ML_CHECKS", "0") == "1":
        optional_py.append(_check_import("gliner", "gliner"))
        optional_py.append(_check_module_spec("paddleocr", "paddleocr"))
        optional_py.append(_check_shared_lib("libGL.so.1", hint="Install system package: apt-get install libgl1"))

    checks.extend(required_py)
    checks.extend(optional_py)

    # System commands
    cmd_checks = [
        _check_cmd("tesseract"),
        _check_cmd("pdfinfo"),
        _check_cmd("pdftoppm"),
    ]
    checks.extend(cmd_checks)

    # Tesseract languages
    tess_lang = _check_tesseract_lang("deu")
    checks.append(tess_lang)

    # Writable dirs
    fs_checks = [
        _check_writeable_dir(data_dir / "tmp"),
        _check_writeable_dir(data_dir / "eingang"),
        _check_writeable_dir(data_dir / "fertig"),
        _check_writeable_dir(data_dir / "logs"),
    ]
    checks.extend(fs_checks)

    # Optional: auto-install python deps (only when required imports fail)
    auto_pip = os.getenv("DOCARO_AUTO_PIP_INSTALL", "0") == "1"
    missing_required = [c for c in required_py if not c.ok]
    if auto_pip and missing_required:
        req = base_dir / "requirements.txt"
        if req.exists():
            checks.append(
                CheckResult(
                    True,
                    "pip:autofix",
                    detail=f"attempting install because missing: {[c.name for c in missing_required]}",
                )
            )
            checks.append(_pip_install_requirements(req))

            # Re-check required imports
            checks.extend(
                [
                    _check_import("flask", "flask"),
                    _check_import("argon2", "argon2-cffi"),
                    _check_import("pdf2image", "pdf2image"),
                    _check_import("pytesseract", "pytesseract"),
                    _check_import("PIL", "pillow"),
                    _check_import("dateutil", "python-dateutil"),
                    _check_import("PyPDF2", "PyPDF2"),
                    _check_import("pdfplumber", "pdfplumber"),
                    _check_import("yaml", "PyYAML"),
                ]
            )

            # Re-check optional imports
            checks.append(_check_import("fitz", "pymupdf"))
            if os.getenv("DOCARO_ML_CHECKS", "0") == "1":
                checks.append(_check_import("gliner", "gliner"))
                checks.append(_check_module_spec("paddleocr", "paddleocr"))
                checks.append(
                    _check_shared_lib(
                        "libGL.so.1",
                        hint="Install system package: apt-get install libgl1",
                    )
                )

    ok = all(c.ok for c in required_py) and all(c.ok for c in cmd_checks) and tess_lang.ok and all(
        c.ok for c in fs_checks
    )

    payload = {
        "ok": ok,
        "python": sys.executable,
        "base_dir": str(base_dir),
        "checks": [c.__dict__ for c in checks],
    }
    print(json.dumps(payload, ensure_ascii=False))

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
