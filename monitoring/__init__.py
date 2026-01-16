"""
Monitoring Package für Docaro.

Structured Logging und Metriken-Tracking.
"""

import logging
import structlog
from pathlib import Path
from typing import Any, Dict

__all__ = ['setup_logging', 'log_pipeline_step']


def setup_logging(log_dir: Path = None, level: int = logging.INFO):
    """
    Konfiguriert Structured Logging mit structlog.
    
    Args:
        log_dir: Verzeichnis für Log-Dateien
        level: Log-Level (default: INFO)
    """
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
    
    # Structlog-Konfiguration
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Standard-Logging
    logging.basicConfig(
        format="%(message)s",
        level=level,
    )


def log_pipeline_step(step: str, pdf_path: Path = None, **kwargs):
    """
    Loggt einen Pipeline-Schritt.
    
    Args:
        step: Name des Schritts
        pdf_path: Pfad zur verarbeiteten PDF
        **kwargs: Zusätzliche Metadaten
    """
    logger = structlog.get_logger()
    
    log_data = {
        'step': step,
        **kwargs
    }
    
    if pdf_path:
        log_data['pdf'] = pdf_path.name
    
    logger.info("pipeline_step", **log_data)
