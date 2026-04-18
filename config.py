import os
import sys
import logging
import json
from pathlib import Path
from logging.handlers import RotatingFileHandler


def _resolve_runtime_base_dir() -> Path:
    override = os.getenv("DOCARO_RUNTIME_BASE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class Config:
    # Repo root (D:\Docaro) – config.py liegt im Root-Verzeichnis.
    BASE_DIR = _resolve_runtime_base_dir()
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
    PADDLEOCR_ENSEMBLE_FIELDS = (
        os.getenv("DOCARO_PADDLEOCR_ENSEMBLE_FIELDS", "0") == "1"
    )  # Ensemble für kritische Felder
    OCR_VARIANT_RETRY_SCORE = int(os.getenv("DOCARO_OCR_VARIANT_RETRY_SCORE", "520"))
    OCR_MIN_UPSCALE_LONG_SIDE = int(os.getenv("DOCARO_OCR_MIN_UPSCALE_LONG_SIDE", "1800"))
    OCR_MIN_UPSCALE_SHORT_SIDE = int(os.getenv("DOCARO_OCR_MIN_UPSCALE_SHORT_SIDE", "1200"))
    # Tabellen-Intelligence (inspiriert von HF Spaces wie Table-to-CSV / table-extraction)
    TABLE_INTELLIGENCE_ENABLED = os.getenv("DOCARO_TABLE_INTELLIGENCE_ENABLED", "1") == "1"
    TABLE_INTELLIGENCE_MAX_PAGES = int(os.getenv("DOCARO_TABLE_INTELLIGENCE_MAX_PAGES", "2"))
    HF_TABLE_WEBHOOK = os.getenv("DOCARO_HF_TABLE_WEBHOOK", "")
    HF_TABLE_TIMEOUT_SECONDS = float(os.getenv("DOCARO_HF_TABLE_TIMEOUT_SECONDS", "6"))
    # Optional: LLM-Assist (z.B. Ollama lokal) für unsichere Dokumente
    LLM_ASSIST_ENABLED = os.getenv("DOCARO_LLM_ASSIST_ENABLED", "0") == "1"
    LLM_ASSIST_MODEL = os.getenv("DOCARO_LLM_ASSIST_MODEL", "llama3.1:8b-instruct")
    LLM_ASSIST_ENDPOINT = os.getenv("DOCARO_LLM_ASSIST_ENDPOINT", "http://127.0.0.1:11434")
    LLM_ASSIST_TIMEOUT_SECONDS = float(os.getenv("DOCARO_LLM_ASSIST_TIMEOUT_SECONDS", "12"))
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

    # Semantische Suche / Embeddings
    VECTOR_BACKEND = os.getenv("DOCARO_VECTOR_BACKEND", "chroma")
    VECTOR_COLLECTION = os.getenv("DOCARO_VECTOR_COLLECTION", "docaro_documents")
    EMBEDDING_PROFILE = os.getenv("DOCARO_EMBEDDING_PROFILE", "sentence-transformers")
    EMBEDDING_MODEL = os.getenv("DOCARO_EMBEDDING_MODEL")

    # Seed-User (optional). Passwort NIE committen, nur via ENV setzen.
    SEED_EMAIL_DEFAULT = os.getenv("DOCARO_SEED_EMAIL", "admin@docaro.local")

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

                subprocess.run(["attrib", "+H", str(Config.SECRET_KEY_FILE)], check=False, capture_output=True)
        except Exception:
            pass
        return new_key

    @staticmethod
    def setup_logging():
        """Richtet zentrales Logging ein."""
        logger = logging.getLogger()
        logger.setLevel(logging.INFO if not Config.DEBUG else logging.DEBUG)
        logger.handlers.clear()

        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)

        log_format = os.getenv("DOCARO_LOG_FORMAT", "text").strip().lower()

        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info:
                    payload["exc_info"] = self.formatException(record.exc_info)
                return json.dumps(payload, ensure_ascii=True)

        if log_format == "json":
            formatter: logging.Formatter = JsonFormatter()
        else:
            formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

        # File Handler mit Rotation
        file_handler = RotatingFileHandler(
            Config.LOG_DIR / "docaro.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB
        )
        file_handler.setLevel(logging.INFO if not Config.DEBUG else logging.DEBUG)
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
