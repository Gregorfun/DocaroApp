from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import fitz

from core import pdf_toolkit


def test_build_ocr_process_env_uses_bundled_tesseract(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    bundle_dir = repo_root / "Tesseract OCR Windows installer"
    bundle_dir.mkdir(parents=True)
    exe_path = bundle_dir / "tesseract.exe"
    exe_path.write_bytes(b"")
    tessdata_dir = bundle_dir / "tessdata"
    tessdata_dir.mkdir()

    monkeypatch.setattr(pdf_toolkit, "BASE_DIR", repo_root)
    monkeypatch.delenv("DOCARO_TESSERACT_CMD", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    env = pdf_toolkit._build_ocr_process_env()

    assert env["DOCARO_TESSERACT_CMD"] == str(exe_path)
    assert env["TESSDATA_PREFIX"] == str(tessdata_dir)
    assert env["PATH"].split(os.pathsep)[0] == str(bundle_dir)


def test_ocr_pdf_passes_configured_env_to_ocrmypdf(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    bundle_dir = repo_root / "Tesseract OCR Windows installer"
    bundle_dir.mkdir(parents=True)
    exe_path = bundle_dir / "tesseract.exe"
    exe_path.write_bytes(b"")
    tessdata_dir = bundle_dir / "tessdata"
    tessdata_dir.mkdir()

    monkeypatch.setattr(pdf_toolkit, "BASE_DIR", repo_root)
    monkeypatch.delenv("DOCARO_TESSERACT_CMD", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    captured: dict[str, object] = {}

    def fake_run(args, capture_output, text, env, timeout):
        captured["args"] = args
        captured["env"] = env
        Path(args[-1]).write_bytes(b"%PDF-1.4\n%ocrmypdf")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(pdf_toolkit.subprocess, "run", fake_run)

    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(input_path))
    doc.close()

    result = pdf_toolkit.ocr_pdf(input_path, output_path, lang="deu+eng")

    assert result == output_path
    assert output_path.exists()
    env = captured["env"]
    assert env["DOCARO_TESSERACT_CMD"] == str(exe_path)
    assert env["TESSDATA_PREFIX"] == str(tessdata_dir)
    assert env["PATH"].split(os.pathsep)[0] == str(bundle_dir)
    assert "--optimize" in captured["args"]
    optimize_index = captured["args"].index("--optimize")
    assert captured["args"][optimize_index + 1] == "0"


def test_ocr_pdf_respects_explicit_optimize_override(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    bundle_dir = repo_root / "Tesseract OCR Windows installer"
    bundle_dir.mkdir(parents=True)
    exe_path = bundle_dir / "tesseract.exe"
    exe_path.write_bytes(b"")
    tessdata_dir = bundle_dir / "tessdata"
    tessdata_dir.mkdir()

    monkeypatch.setattr(pdf_toolkit, "BASE_DIR", repo_root)
    monkeypatch.setenv("DOCARO_OCRMYPDF_OPTIMIZE", "1")
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.delenv("DOCARO_TESSERACT_CMD", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    captured: dict[str, object] = {}

    def fake_run(args, capture_output, text, env, timeout):
        captured["args"] = args
        Path(args[-1]).write_bytes(b"%PDF-1.4\n%ocrmypdf")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(pdf_toolkit.subprocess, "run", fake_run)

    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(input_path))
    doc.close()

    pdf_toolkit.ocr_pdf(input_path, output_path, lang="deu+eng")

    optimize_index = captured["args"].index("--optimize")
    assert captured["args"][optimize_index + 1] == "1"


def test_ocr_pdf_uses_fallback_in_frozen_mode(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    bundle_dir = repo_root / "Tesseract OCR Windows installer"
    bundle_dir.mkdir(parents=True)

    monkeypatch.setattr(pdf_toolkit, "BASE_DIR", repo_root)
    monkeypatch.setattr(pdf_toolkit.sys, "frozen", True, raising=False)

    captured: dict[str, object] = {}

    def fake_fallback(input_path, output_path, lang):
        captured["lang"] = lang
        Path(output_path).write_bytes(b"%PDF-1.4\n%ocr-fallback")

    monkeypatch.setattr(pdf_toolkit, "_ocr_fallback", fake_fallback)
    monkeypatch.setattr(pdf_toolkit.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess should not be used in frozen mode")))

    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(input_path))
    doc.close()

    result = pdf_toolkit.ocr_pdf(input_path, output_path, lang="deu+eng")

    assert result == output_path
    assert output_path.exists()
    assert captured["lang"] == "deu+eng"