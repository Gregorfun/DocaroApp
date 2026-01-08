import os
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

class Config:
    # Repo root (D:\Docaro) – config.py liegt im Root-Verzeichnis.
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"
    LOG_DIR = DATA_DIR / "logs"

    # App-Verzeichnisse / Dateien
    INBOX_DIR = DATA_DIR / "eingang"
    OUT_DIR = DATA_DIR / "fertig"
    TMP_DIR = DATA_DIR / "tmp"
    SUPPLIER_CORRECTIONS_PATH = DATA_DIR / "supplier_corrections.json"
    SESSION_FILES_PATH = DATA_DIR / "session_files.json"
    # Lock-Datei für Cross-Process File Locking (siehe app/_locked_file)
    SESSION_FILES_LOCK = DATA_DIR / "session_files.lock"
    HISTORY_PATH = DATA_DIR / "history.jsonl"
    SECRET_KEY = os.getenv("DOCARO_SECRET_KEY")
    DEBUG = os.getenv("DOCARO_DEBUG") == "1"
    OCR_TIMEOUT_SECONDS = int(os.getenv("DOCARO_OCR_TIMEOUT", "20"))
    PDF_CONVERT_TIMEOUT = int(os.getenv("DOCARO_PDF_CONVERT_TIMEOUT", "30"))
    ROTATION_OCR_TIMEOUT = int(os.getenv("DOCARO_ROTATION_OCR_TIMEOUT", "10"))
    DATE_CROP_OCR_TIMEOUT = int(os.getenv("DOCARO_DATE_CROP_OCR_TIMEOUT", "5"))
    OCR_PAGES = int(os.getenv("DOCARO_OCR_PAGES", "3"))
    LOG_RETENTION_DAYS = int(os.getenv("DOCARO_LOG_RETENTION_DAYS", "30"))
    DEBUG_EXTRACT = os.getenv("DOCARO_DEBUG_EXTRACT") == "1"
    TESSERACT_CMD = os.getenv("DOCARO_TESSERACT_CMD")
    POPPLER_BIN = os.getenv("DOCARO_POPPLER_BIN")

    @staticmethod
    def setup_logging():
        """Richtet zentrales Logging ein."""
        logger = logging.getLogger()
        logger.setLevel(logging.INFO if not Config.DEBUG else logging.DEBUG)

        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # File Handler mit Rotation
        file_handler = RotatingFileHandler(
            Config.LOG_DIR / "docaro.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO if not Config.DEBUG else logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console Handler für Debug
        if Config.DEBUG:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        return logger