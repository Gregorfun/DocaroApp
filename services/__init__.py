"""Docaro service exports with lazy loading for optional integrations."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["VectorService", "store_embeddings", "MLflowService"]


def __getattr__(name: str) -> Any:
    if name in {"VectorService", "store_embeddings"}:
        module = import_module("services.vector_service")
        return getattr(module, name)
    if name == "MLflowService":
        module = import_module("services.mlflow_service")
        return getattr(module, name)
    raise AttributeError(f"module 'services' has no attribute {name!r}")
