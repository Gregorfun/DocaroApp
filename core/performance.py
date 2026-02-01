"""
Performance Utilities - Profiling & Monitoring.
"""

import time
import logging
from functools import wraps
from typing import Any, Callable

_logger = logging.getLogger(__name__)


def profile(threshold_seconds: float = 1.0):
    """
    Decorator für Performance-Messung.
    
    Loggt Funktionen die länger als threshold_seconds brauchen.
    
    Args:
        threshold_seconds: Minimale Zeit in Sekunden, ab der geloggt wird
    
    Beispiel:
        @profile(0.5)
        def slow_function():
            time.sleep(1)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                if elapsed > threshold_seconds:
                    _logger.warning(
                        f"⚠️ Performance: {func.__name__} took {elapsed:.2f}s "
                        f"(threshold: {threshold_seconds}s)"
                    )
        return wrapper
    return decorator


def profile_always(func: Callable) -> Callable:
    """
    Decorator für Performance-Messung ohne Threshold.
    
    Loggt jede Ausführung mit Zeitmessung.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            _logger.info(f"⏱️ {func.__name__} completed in {elapsed:.3f}s")
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - start
            _logger.error(f"❌ {func.__name__} failed after {elapsed:.3f}s: {exc}")
            raise
    return wrapper
