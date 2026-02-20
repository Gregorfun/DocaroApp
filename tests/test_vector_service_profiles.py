from __future__ import annotations

import pytest

from services.vector_service import VectorService


def test_resolve_default_profile() -> None:
    provider, model, dense = VectorService._resolve_embedding_profile(
        embedding_profile="sentence-transformers",
        embedding_model=None,
    )
    assert provider == "sentence_transformers"
    assert model == "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    assert dense is True


def test_resolve_bimodern_with_model_override() -> None:
    provider, model, dense = VectorService._resolve_embedding_profile(
        embedding_profile="bimodernvbert",
        embedding_model="ModernVBERT/bimodernvbert",
    )
    assert provider == "modernvbert"
    assert model == "ModernVBERT/bimodernvbert"
    assert dense is True


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="Unbekanntes embedding_profile"):
        VectorService._resolve_embedding_profile("does-not-exist", None)


def test_colqwen_qdrant_blocked() -> None:
    with pytest.raises(ValueError, match="Dense-Embeddings"):
        VectorService(backend="qdrant", embedding_profile="colqwen2-v1")


def test_qdrant_existing_size_from_named_vectors() -> None:
    service = VectorService()

    class _NamedCfg:
        size = 512

    class _Params:
        vectors = {"doc": _NamedCfg()}

    class _Config:
        params = _Params()

    class _Details:
        config = _Config()

    class _Client:
        @staticmethod
        def get_collection(collection_name: str):
            return _Details()

    dim = service._qdrant_get_existing_vector_size(_Client())
    assert dim == 512
