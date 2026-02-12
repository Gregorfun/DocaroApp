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
    QUARANTINE_DIR = DATA_DIR / "quarantaene"
    SETTINGS_PATH = DATA_DIR / "settings.json"
    AUTH_DIR = DATA_DIR / "auth"
    AUTH_DB_PATH = AUTH_DIR / "auth.db"
    SUPPLIER_CORRECTIONS_PATH = DATA_DIR / "supplier_corrections.json"
    SESSION_FILES_PATH = DATA_DIR / "session_files.json"
    # Lock-Datei für Cross-Process File Locking (siehe app/_locked_file)
    SESSION_FILES_LOCK = DATA_DIR / "session_files.lock"
    HISTORY_PATH = DATA_DIR / "history.jsonl"
    SECRET_KEY_FILE = DATA_DIR / ".secret_key"
    SECRET_KEY: str | None = None
    DEBUG = os.getenv("DOCARO_DEBUG") == "1"
    OCR_TIMEOUT_SECONDS = int(os.getenv("DOCARO_OCR_TIMEOUT", "25"))
    PDF_CONVERT_TIMEOUT = int(os.getenv("DOCARO_PDF_CONVERT_TIMEOUT", "15"))
    ROTATION_OCR_TIMEOUT = int(os.getenv("DOCARO_ROTATION_OCR_TIMEOUT", "4"))
    DATE_CROP_OCR_TIMEOUT = int(os.getenv("DOCARO_DATE_CROP_TIMEOUT", "3"))
    OCR_PAGES = int(os.getenv("DOCARO_OCR_PAGES", "2"))
    LOG_RETENTION_DAYS = int(os.getenv("DOCARO_LOG_RETENTION_DAYS", "30"))
    DEBUG_EXTRACT = os.getenv("DOCARO_DEBUG_EXTRACT") == "1"
    # Optional: KI-OCR (PaddleOCR) als Fallback bei schwierigen Scan-PDFs
    USE_PADDLEOCR = os.getenv("DOCARO_USE_PADDLEOCR", "0") == "1"
    PADDLEOCR_LANG = os.getenv("DOCARO_PADDLEOCR_LANG", "german")
    PADDLEOCR_FALLBACK_THRESHOLD = int(os.getenv("DOCARO_PADDLEOCR_FALLBACK_THRESHOLD", "400"))  # Score-Schwelle
    PADDLEOCR_ENSEMBLE_FIELDS = os.getenv("DOCARO_PADDLEOCR_ENSEMBLE_FIELDS", "0") == "1"  # Ensemble für kritische Felder
    TESSERACT_CMD = os.getenv("DOCARO_TESSERACT_CMD")
    POPPLER_BIN = os.getenv("DOCARO_POPPLER_BIN")
    # Auto-Sort Defaults (können via Settings-Seite überschrieben werden)
    AUTO_SORT_ENABLED_DEFAULT = os.getenv("DOCARO_AUTOSORT_ENABLED", "0") == "1"
    AUTO_SORT_BASE_DIR_DEFAULT = Path(os.getenv("DOCARO_AUTOSORT_BASE", str(DATA_DIR / "fertig")))
    AUTO_SORT_FOLDER_FORMAT_DEFAULT = os.getenv("DOCARO_AUTOSORT_FOLDER_FORMAT", "A")
    AUTO_SORT_MODE_DEFAULT = os.getenv("DOCARO_AUTOSORT_MODE", "move")
    AUTO_SORT_CONFIDENCE_THRESHOLD_DEFAULT = float(os.getenv("DOCARO_AUTOSORT_CONF", "0.80"))
    AUTO_SORT_FALLBACK_FOLDER_DEFAULT = os.getenv("DOCARO_AUTOSORT_FALLBACK", "_Unsortiert (Prüfen)")
    # Optional: rekursive Dateisuche (langsamer, findet aber mehr Dateien)
    DEEP_SCAN = os.getenv("DOCARO_DEEP_SCAN", "0") == "1"
    # Server-Einstellungen
    SERVER_HOST = os.getenv("DOCARO_SERVER_HOST", "127.0.0.1")
    SERVER_PORT = int(os.getenv("DOCARO_SERVER_PORT", "5001"))
    SERVER_USE_RELOADER = os.getenv("DOCARO_SERVER_USE_RELOADER", "0") == "1"

    # Seed-User (optional). Passwort NIE committen, nur via ENV setzen.
    SEED_EMAIL_DEFAULT = os.getenv("DOCARO_SEED_EMAIL", "g.machuletz@bracht-autokrane.de")

    @staticmethod
    def _get_or_create_secret_key() -> str:
        """Generiert oder lädt den persistenten SECRET_KEY."""
        import secrets
        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if Config.SECRET_KEY_FILE.exists():
            try:
                return Config.SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        # Neuen Key generieren
        new_key = secrets.token_hex(32)
        try:
            Config.SECRET_KEY_FILE.write_text(new_key, encoding="utf-8")
            # Datei verstecken (Windows)
            if os.name == "nt":
                import subprocess
                subprocess.run(["attrib", "+H", str(Config.SECRET_KEY_FILE)], 
                             check=False, capture_output=True)
        except Exception:
            pass
        return new_key

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


# SECRET_KEY muss nach der Klassendefinition initialisiert werden,
# weil der Name "Config" innerhalb des Klassen-Bodys noch nicht gebunden ist.
Config.SECRET_KEY = os.getenv("DOCARO_SECRET_KEY") or Config._get_or_create_secret_key()