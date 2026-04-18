import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _resolve_runtime_base_dir() -> Path:
    override = os.getenv("DOCARO_RUNTIME_BASE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip().replace(",", ".")
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _clamp_int(value: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def _clamp_float(value: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


class Config:
    BASE_DIR = _resolve_runtime_base_dir()
    DATA_DIR = BASE_DIR / "data"
    LOG_DIR = DATA_DIR / "logs"

    INBOX_DIR = DATA_DIR / "eingang"
    OUT_DIR = DATA_DIR / "fertig"
    TMP_DIR = DATA_DIR / "tmp"
    QUARANTINE_DIR = DATA_DIR / "quarantaene"
    SETTINGS_PATH = DATA_DIR / "settings.json"
    AUTH_DIR = DATA_DIR / "auth"
    AUTH_DB_PATH = AUTH_DIR / "auth.db"
    SUPPLIER_CORRECTIONS_PATH = DATA_DIR / "supplier_corrections.json"
    SESSION_FILES_PATH = DATA_DIR / "session_files.json"
    SESSION_FILES_LOCK = DATA_DIR / "session_files.lock"
    HISTORY_PATH = DATA_DIR / "history.jsonl"
    SECRET_KEY_FILE = DATA_DIR / ".secret_key"
    SECRET_KEY: str | None = None

    DEBUG = _env_bool("DOCARO_DEBUG", False)
    OCR_TIMEOUT_SECONDS = _clamp_int(_env_int("DOCARO_OCR_TIMEOUT", 25), minimum=1)
    PDF_CONVERT_TIMEOUT = _clamp_int(_env_int("DOCARO_PDF_CONVERT_TIMEOUT", 15), minimum=1)
    ROTATION_OCR_TIMEOUT = _clamp_int(_env_int("DOCARO_ROTATION_OCR_TIMEOUT", 4), minimum=1)
    DATE_CROP_OCR_TIMEOUT = _clamp_int(_env_int("DOCARO_DATE_CROP_TIMEOUT", 3), minimum=1)
    OCR_PAGES = _clamp_int(_env_int("DOCARO_OCR_PAGES", 2), minimum=1)
    LOG_RETENTION_DAYS = _clamp_int(_env_int("DOCARO_LOG_RETENTION_DAYS", 30), minimum=0)
    DEBUG_EXTRACT = _env_bool("DOCARO_DEBUG_EXTRACT", False)

    USE_PADDLEOCR = _env_bool("DOCARO_USE_PADDLEOCR", False)
    PADDLEOCR_LANG = os.getenv("DOCARO_PADDLEOCR_LANG", "german")
    PADDLEOCR_FALLBACK_THRESHOLD = _clamp_int(_env_int("DOCARO_PADDLEOCR_FALLBACK_THRESHOLD", 400), minimum=0)
    PADDLEOCR_ENSEMBLE_FIELDS = _env_bool("DOCARO_PADDLEOCR_ENSEMBLE_FIELDS", False)
    OCR_VARIANT_RETRY_SCORE = _clamp_int(_env_int("DOCARO_OCR_VARIANT_RETRY_SCORE", 520), minimum=0)
    OCR_MIN_UPSCALE_LONG_SIDE = _clamp_int(_env_int("DOCARO_OCR_MIN_UPSCALE_LONG_SIDE", 1800), minimum=1)
    OCR_MIN_UPSCALE_SHORT_SIDE = _clamp_int(_env_int("DOCARO_OCR_MIN_UPSCALE_SHORT_SIDE", 1200), minimum=1)

    TABLE_INTELLIGENCE_ENABLED = _env_bool("DOCARO_TABLE_INTELLIGENCE_ENABLED", True)
    TABLE_INTELLIGENCE_MAX_PAGES = _clamp_int(_env_int("DOCARO_TABLE_INTELLIGENCE_MAX_PAGES", 2), minimum=1)
    HF_TABLE_WEBHOOK = os.getenv("DOCARO_HF_TABLE_WEBHOOK", "")
    HF_TABLE_TIMEOUT_SECONDS = _clamp_float(_env_float("DOCARO_HF_TABLE_TIMEOUT_SECONDS", 6.0), minimum=0.1)

    LLM_ASSIST_ENABLED = _env_bool("DOCARO_LLM_ASSIST_ENABLED", False)
    LLM_ASSIST_MODEL = os.getenv("DOCARO_LLM_ASSIST_MODEL", "llama3.1:8b-instruct")
    LLM_ASSIST_ENDPOINT = os.getenv("DOCARO_LLM_ASSIST_ENDPOINT", "http://127.0.0.1:11434")
    LLM_ASSIST_TIMEOUT_SECONDS = _clamp_float(_env_float("DOCARO_LLM_ASSIST_TIMEOUT_SECONDS", 12.0), minimum=0.1)

    TESSERACT_CMD = os.getenv("DOCARO_TESSERACT_CMD")
    POPPLER_BIN = os.getenv("DOCARO_POPPLER_BIN")

    AUTO_SORT_ENABLED_DEFAULT = _env_bool("DOCARO_AUTOSORT_ENABLED", False)
    AUTO_SORT_BASE_DIR_DEFAULT = Path(os.getenv("DOCARO_AUTOSORT_BASE", str(DATA_DIR / "fertig")))
    AUTO_SORT_FOLDER_FORMAT_DEFAULT = os.getenv("DOCARO_AUTOSORT_FOLDER_FORMAT", "A")
    AUTO_SORT_MODE_DEFAULT = os.getenv("DOCARO_AUTOSORT_MODE", "move")
    AUTO_SORT_CONFIDENCE_THRESHOLD_DEFAULT = _clamp_float(_env_float("DOCARO_AUTOSORT_CONF", 0.80), minimum=0.0, maximum=1.0)
    AUTO_SORT_FALLBACK_FOLDER_DEFAULT = os.getenv("DOCARO_AUTOSORT_FALLBACK", "_Unsortiert (Prüfen)")

    DEEP_SCAN = _env_bool("DOCARO_DEEP_SCAN", False)
    SERVER_HOST = os.getenv("DOCARO_SERVER_HOST", "127.0.0.1")
    SERVER_PORT = _clamp_int(_env_int("DOCARO_SERVER_PORT", 5001), minimum=1, maximum=65535)
    SERVER_USE_RELOADER = _env_bool("DOCARO_SERVER_USE_RELOADER", False)

    VECTOR_BACKEND = os.getenv("DOCARO_VECTOR_BACKEND", "chroma")
    VECTOR_COLLECTION = os.getenv("DOCARO_VECTOR_COLLECTION", "docaro_documents")
    EMBEDDING_PROFILE = os.getenv("DOCARO_EMBEDDING_PROFILE", "sentence-transformers")
    EMBEDDING_MODEL = os.getenv("DOCARO_EMBEDDING_MODEL")

    SEED_EMAIL_DEFAULT = os.getenv("DOCARO_SEED_EMAIL", "admin@docaro.local")

    @staticmethod
    def _get_or_create_secret_key() -> str:
        import secrets

        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if Config.SECRET_KEY_FILE.exists():
            try:
                return Config.SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        new_key = secrets.token_hex(32)
        try:
            Config.SECRET_KEY_FILE.write_text(new_key, encoding="utf-8")
            if os.name == "nt":
                import subprocess

                subprocess.run(["attrib", "+H", str(Config.SECRET_KEY_FILE)], check=False, capture_output=True)
        except Exception:
            pass
        return new_key

    @staticmethod
    def validation_errors() -> list[str]:
        errors: list[str] = []

        if Config.SERVER_PORT < 1 or Config.SERVER_PORT > 65535:
            errors.append("DOCARO_SERVER_PORT must be between 1 and 65535.")
        if Config.OCR_TIMEOUT_SECONDS < 1:
            errors.append("DOCARO_OCR_TIMEOUT must be >= 1 second.")
        if Config.PDF_CONVERT_TIMEOUT < 1:
            errors.append("DOCARO_PDF_CONVERT_TIMEOUT must be >= 1 second.")
        if Config.OCR_PAGES < 1:
            errors.append("DOCARO_OCR_PAGES must be >= 1.")
        if Config.LOG_RETENTION_DAYS < 0:
            errors.append("DOCARO_LOG_RETENTION_DAYS must be >= 0.")
        if not 0.0 <= Config.AUTO_SORT_CONFIDENCE_THRESHOLD_DEFAULT <= 1.0:
            errors.append("DOCARO_AUTOSORT_CONF must be between 0.0 and 1.0.")

        upload_canary = _env_int("DOCARO_UPLOAD_CANARY_PERCENT", 0)
        csrf_canary = _env_int("DOCARO_CSRF_CANARY_PERCENT", 0)
        if not 0 <= upload_canary <= 100:
            errors.append("DOCARO_UPLOAD_CANARY_PERCENT must be between 0 and 100.")
        if not 0 <= csrf_canary <= 100:
            errors.append("DOCARO_CSRF_CANARY_PERCENT must be between 0 and 100.")

        folder_format = str(Config.AUTO_SORT_FOLDER_FORMAT_DEFAULT or "").upper()
        if folder_format not in {"A", "B", "C"}:
            errors.append("DOCARO_AUTOSORT_FOLDER_FORMAT must be one of A, B or C.")
        mode = str(Config.AUTO_SORT_MODE_DEFAULT or "").lower()
        if mode not in {"move", "copy"}:
            errors.append("DOCARO_AUTOSORT_MODE must be 'move' or 'copy'.")

        return errors

    @staticmethod
    def validate_runtime_configuration(*, raise_on_error: bool = False) -> list[str]:
        errors = Config.validation_errors()
        if errors and raise_on_error:
            raise ValueError("Invalid Docaro configuration: " + " | ".join(errors))
        return errors

    @staticmethod
    def setup_logging():
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

        formatter: logging.Formatter
        if log_format == "json":
            formatter = JsonFormatter()
        else:
            formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

        file_handler = RotatingFileHandler(
            Config.LOG_DIR / "docaro.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO if not Config.DEBUG else logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        if Config.DEBUG:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        return logger


Config.SECRET_KEY = os.getenv("DOCARO_SECRET_KEY") or Config._get_or_create_secret_key()
