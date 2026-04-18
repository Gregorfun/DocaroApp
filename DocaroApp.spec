# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec fuer DocaroApp Desktop.
Build: pyinstaller DocaroApp.spec
"""

import sys
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
bundled_tesseract_dir = ROOT / "Tesseract OCR Windows installer"

datas = [
    # Templates und Static Files
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
    # fakeredis Datendatei
    (str(ROOT / ".venv" / "Lib" / "site-packages" / "fakeredis" / "commands.json"), "fakeredis"),
    # Konfiguration und Kern-Module
    (str(ROOT / "config.py"), "."),
    (str(ROOT / "constants.py"), "."),
    (str(ROOT / "utils.py"), "."),
    (str(ROOT / "date_parser.py"), "."),
    # Core-Module
    (str(ROOT / "core"), "core"),
    # Services
    (str(ROOT / "services"), "services"),
    # Pipelines
    (str(ROOT / "pipelines"), "pipelines"),
]
if bundled_tesseract_dir.exists():
    datas.append((str(bundled_tesseract_dir), "Tesseract OCR Windows installer"))
datas += collect_data_files("ocrmypdf")


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


hiddenimports = [
    # Flask-Oekosystem
    "flask", "flask.templating", "jinja2", "werkzeug",
    "werkzeug.routing", "werkzeug.serving", "werkzeug.exceptions",
    # App-interne Module
    "app.app", "app.review_routes", "app.pdf_toolkit_routes",
    "app.runtime_storage", "app.queue_runtime",
    # Core
    "core.extractor", "core.review_service", "core.pdf_toolkit",
    "core.supplier_canonicalizer", "core.doc_number_extractor",
    "core.doctype_classifier", "core.date_scorer", "core.metrics",
    "core.audit_logger", "core.quarantine_manager", "core.llm_assist",
    "core.runtime_store",
    # Services
    "services.auth_store", "services.web_auth", "services.auto_sort",
    "services.worker",
    # Queue
    "rq", "rq.job", "rq.worker", "rq.queue", "rq.command",
    "rq.serializers", "rq.timeouts", "rq.decorators",
    "fakeredis",
    # PDF
    "fitz", "PyPDF2", "pdfplumber", "pdf2image", "PIL", "PIL.Image",
    "pymupdf", "pikepdf", "img2pdf",
    # ML / NLP (lazy)
    "sklearn", "sklearn.feature_extraction.text",
    "sklearn.linear_model", "sklearn.pipeline",
    # Sonstiges
    "pytesseract", "dateutil", "dateutil.parser",
    "structlog", "argon2",
    "sqlite3", "json", "zipfile", "hashlib", "hmac",
    # PyWebView
    "webview", "webview.platforms.winforms",
    "clr", "System", "System.Windows.Forms",
    "pythonnet",
]

hiddenimports = [name for name in hiddenimports if _module_available(name)] + collect_submodules("ocrmypdf")

a = Analysis(
    [str(ROOT / "desktop_app.py")],
    pathex=[str(ROOT), str(ROOT / "app")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Schwere optionale Abhaengigkeiten weglassen
        "torch", "torchvision", "transformers",
        "paddleocr", "paddlepaddle",
        "docling", "docling_core",
        "qdrant_client", "chromadb",
        "mlflow", "evidently",
        "label_studio",
        "matplotlib", "scipy",
        "IPython", "notebook",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DocaroApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DocaroApp",
)