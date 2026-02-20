"""
Vector-Service für semantische Suche mit Qdrant oder Chroma.

Ermöglicht:
- Speicherung von Dokument-Embeddings
- Semantische Suche ("finde ähnliche Dokumente")
- Duplikaterkennung
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_LOGGER = logging.getLogger(__name__)


_MODEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "sentence-transformers": {
        "provider": "sentence_transformers",
        "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "dense": True,
    },
    "bimodernvbert": {
        "provider": "modernvbert",
        "model": "ModernVBERT/bimodernvbert",
        "dense": True,
    },
    "colqwen2-v1": {
        "provider": "colqwen2",
        "model": "vidore/colqwen2-v1.0-hf",
        "dense": False,
    },
}


@dataclass
class SearchResult:
    """Ergebnis einer semantischen Suche."""

    id: str
    score: float
    metadata: Dict[str, Any]


class VectorService:
    """
    Abstraction-Layer für Vektordatenbanken.

    Unterstützt:
    - Qdrant (High-Performance, production-ready)
    - Chroma (Lightweight, einfache Nutzung)

    Embedding-Profile:
    - sentence-transformers (Dense, produktiv)
    - bimodernvbert (Dense, visuelle Retrieval-Optimierung)
    - colqwen2-v1 (Late-Interaction, nur Benchmark-Pfad)
    """

    def __init__(
        self,
        backend: str = "chroma",  # "qdrant" oder "chroma"
        collection_name: str = "docaro_documents",
        embedding_model: Optional[str] = None,
        embedding_profile: str = "sentence-transformers",
    ):
        """
        Args:
            backend: "qdrant" oder "chroma"
            collection_name: Name der Collection
            embedding_model: Optionales Override des Modellnamens
            embedding_profile: vordefiniertes Profil (z.B. "bimodernvbert")
        """
        self.backend = backend
        self.collection_name = collection_name

        self.embedding_profile = embedding_profile
        self.embedding_provider, self.embedding_model_name, self.is_dense_embedding = self._resolve_embedding_profile(
            embedding_profile=embedding_profile,
            embedding_model=embedding_model,
        )

        if self.backend == "qdrant" and not self.is_dense_embedding:
            raise ValueError(
                "Qdrant-Integration in Docaro erwartet Dense-Embeddings. "
                f"Profil '{embedding_profile}' ist Late-Interaction und wird hier nicht unterstützt."
            )

        self._client = None
        self._embedding_model = None
        self._embedding_processor = None
        self._embedding_dim: Optional[int] = None

    @staticmethod
    def _resolve_embedding_profile(
        embedding_profile: str,
        embedding_model: Optional[str],
    ) -> Tuple[str, str, bool]:
        """Löst Profil + optionales Modell-Override auf Provider-Konfiguration auf."""
        key = (embedding_profile or "sentence-transformers").strip().lower()
        profile = _MODEL_PROFILES.get(key)

        if profile is None:
            valid = ", ".join(sorted(_MODEL_PROFILES.keys()))
            raise ValueError(f"Unbekanntes embedding_profile='{embedding_profile}'. Gültig: {valid}")

        model_name = embedding_model or profile["model"]
        return profile["provider"], model_name, bool(profile["dense"])

    def _get_client(self):
        """Lazy-Loading des DB-Clients."""
        if self._client is not None:
            return self._client

        if self.backend == "qdrant":
            self._client = self._init_qdrant()
        elif self.backend == "chroma":
            self._client = self._init_chroma()
        else:
            raise ValueError(f"Unbekannter Backend: {self.backend}")

        return self._client

    def _init_qdrant(self):
        """
        Initialisiert Qdrant-Client.

        **Setup**:
        ```bash
        docker run -p 6333:6333 qdrant/qdrant
        ```

        **Nutzen**:
        - High-Performance (1M+ Vektoren)
        - Advanced Filtering
        - Clustering & Indexing
        """
        try:
            from qdrant_client import QdrantClient
        except ImportError:
            raise ImportError(
                "Qdrant ist nicht installiert. "
                "Installiere mit: pip install qdrant-client"
            )

        _LOGGER.info("Verbinde mit Qdrant...")
        return QdrantClient(host="localhost", port=6333)

    def _qdrant_get_existing_vector_size(self, client) -> Optional[int]:
        """Liest die konfigurierte Vektordimension einer Collection."""
        try:
            details = client.get_collection(collection_name=self.collection_name)
        except Exception:
            return None

        vectors = getattr(getattr(details, "config", None), "params", None)
        vectors = getattr(vectors, "vectors", None)

        if hasattr(vectors, "size"):
            return int(vectors.size)

        if isinstance(vectors, dict) and vectors:
            first_key = next(iter(vectors))
            cfg = vectors[first_key]
            if hasattr(cfg, "size"):
                return int(cfg.size)
            if isinstance(cfg, dict) and "size" in cfg:
                return int(cfg["size"])

        return None

    def _ensure_qdrant_collection(self, client, embedding_dim: int) -> None:
        """Erstellt/validiert die Collection mit passender Embedding-Dimension."""
        from qdrant_client.models import Distance, VectorParams

        collections = client.get_collections().collections
        collection_names = {c.name for c in collections}

        if self.collection_name not in collection_names:
            _LOGGER.info(
                "Erstelle Qdrant-Collection '%s' mit Dimension %s",
                self.collection_name,
                embedding_dim,
            )
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE,
                ),
            )
            return

        existing_dim = self._qdrant_get_existing_vector_size(client)
        if existing_dim is not None and existing_dim != embedding_dim:
            raise ValueError(
                "Qdrant-Collection-Dimension passt nicht zum Modell: "
                f"collection={existing_dim}, model={embedding_dim}. "
                "Bitte neue Collection nutzen oder bestehende migrieren."
            )

    def _init_chroma(self):
        """
        Initialisiert Chroma-Client.

        **Setup**:
        Keine externe Dependencies, läuft in-memory oder persistent.

        **Nutzen**:
        - Einfache API
        - Lightweight (< 1M Vektoren)
        - In-Memory oder SQLite-backed
        """
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "Chroma ist nicht installiert. "
                "Installiere mit: pip install chromadb"
            )

        _LOGGER.info("Initialisiere Chroma...")

        # Persistent Storage
        from config import Config

        config = Config()
        chroma_path = config.DATA_DIR / "chroma_db"
        chroma_path.mkdir(exist_ok=True)

        client = chromadb.PersistentClient(path=str(chroma_path))

        # Hole oder erstelle Collection
        try:
            collection = client.get_collection(name=self.collection_name)
        except Exception:
            _LOGGER.info("Erstelle Chroma-Collection: %s", self.collection_name)
            collection = client.create_collection(name=self.collection_name)

        return collection

    def _load_sentence_transformer(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers ist nicht installiert. "
                "Installiere mit: pip install sentence-transformers"
            )

        _LOGGER.info("Lade Embedding-Modell (sentence-transformers): %s", self.embedding_model_name)
        self._embedding_model = SentenceTransformer(self.embedding_model_name)

    def _load_modernvbert(self):
        try:
            import torch
            from colpali_engine.models import BiModernVBert, BiModernVBertProcessor
        except ImportError:
            raise ImportError(
                "Für bimodernvbert fehlt colpali-engine/torch. "
                "Installiere mit: pip install colpali-engine torch"
            )

        _LOGGER.info("Lade Embedding-Modell (BiModernVBERT): %s", self.embedding_model_name)
        self._embedding_processor = BiModernVBertProcessor.from_pretrained(self.embedding_model_name)
        self._embedding_model = BiModernVBert.from_pretrained(
            self.embedding_model_name,
            torch_dtype=torch.float32,
            trust_remote_code=True,
        )

        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._embedding_model.to(device)
        self._embedding_model.eval()

    def _get_embedding_model(self):
        """Lazy-Loading des Embedding-Modells."""
        if self._embedding_model is not None:
            return self._embedding_model

        if self.embedding_provider == "sentence_transformers":
            self._load_sentence_transformer()
        elif self.embedding_provider == "modernvbert":
            self._load_modernvbert()
        elif self.embedding_provider == "colqwen2":
            raise ValueError(
                "Profil 'colqwen2-v1' ist Late-Interaction und nicht direkt mit VectorService kompatibel. "
                "Nutze dafür tools/benchmark_visual_retrieval.py."
            )
        else:
            raise ValueError(f"Unbekannter embedding_provider: {self.embedding_provider}")

        return self._embedding_model

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        model = self._get_embedding_model()

        if self.embedding_provider == "sentence_transformers":
            vectors = model.encode(texts)
            return np.asarray(vectors, dtype=np.float32)

        if self.embedding_provider == "modernvbert":
            import torch

            assert self._embedding_processor is not None

            inputs = self._embedding_processor.process_texts(texts)
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model(**inputs)

            if hasattr(outputs, "last_hidden_state"):
                arr = outputs.last_hidden_state
            elif isinstance(outputs, (list, tuple)):
                arr = outputs[0]
            else:
                arr = outputs

            if hasattr(arr, "detach"):
                arr = arr.detach().cpu().numpy()

            arr = np.asarray(arr, dtype=np.float32)
            if arr.ndim == 3:
                # Mean-Pooling über Token-Dimension
                arr = arr.mean(axis=1)
            return arr

        raise ValueError(f"Encoding nicht unterstützt für provider={self.embedding_provider}")

    def _encode_text(self, text: str) -> np.ndarray:
        vectors = self._encode_texts([text])
        return vectors[0]

    def store_embedding(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Speichert Dokument-Embedding.

        Args:
            doc_id: Eindeutige Dokument-ID
            text: Dokumenten-Text
            metadata: Zusätzliche Metadaten (Lieferant, Datum, etc.)

        Returns:
            Gespeicherte ID
        """
        _LOGGER.debug("Speichere Embedding für: %s", doc_id)

        embedding = self._encode_text(text)
        self._embedding_dim = int(embedding.shape[-1])

        client = self._get_client()

        if self.backend == "qdrant":
            return self._store_qdrant(client, doc_id, embedding, metadata or {})
        if self.backend == "chroma":
            return self._store_chroma(client, doc_id, embedding, text, metadata or {})

        raise ValueError(f"Unbekannter Backend: {self.backend}")

    def _store_qdrant(self, client, doc_id: str, embedding: np.ndarray, metadata: Dict):
        """Speichert in Qdrant."""
        from qdrant_client.models import PointStruct

        self._ensure_qdrant_collection(client, int(embedding.shape[-1]))

        point = PointStruct(
            id=hash(doc_id) % (2**63),  # Qdrant benötigt Integer-IDs
            vector=embedding.tolist(),
            payload={
                "doc_id": doc_id,
                **metadata,
            },
        )

        client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )

        return doc_id

    def _store_chroma(self, collection, doc_id: str, embedding: np.ndarray, text: str, metadata: Dict):
        """Speichert in Chroma."""
        collection.add(
            ids=[doc_id],
            embeddings=[embedding.tolist()],
            documents=[text[:1000]],  # Chroma speichert auch Text
            metadatas=[metadata],
        )

        return doc_id

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict] = None,
    ) -> List[SearchResult]:
        """
        Semantische Suche nach ähnlichen Dokumenten.

        Args:
            query_text: Suchtext
            top_k: Anzahl Ergebnisse
            filter_metadata: Metadaten-Filter (z.B. {'supplier': 'XYZ GmbH'})

        Returns:
            Liste von SearchResults
        """
        _LOGGER.debug("Suche: '%s...'", query_text[:50])

        query_embedding = self._encode_text(query_text)
        query_dim = int(query_embedding.shape[-1])

        client = self._get_client()

        if self.backend == "qdrant":
            return self._search_qdrant(client, query_embedding, query_dim, top_k, filter_metadata)
        if self.backend == "chroma":
            return self._search_chroma(client, query_embedding, top_k, filter_metadata)

        raise ValueError(f"Unbekannter Backend: {self.backend}")

    def _search_qdrant(
        self,
        client,
        query_embedding: np.ndarray,
        query_dim: int,
        top_k: int,
        filter_metadata: Optional[Dict],
    ) -> List[SearchResult]:
        """Suche in Qdrant."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        existing_dim = self._qdrant_get_existing_vector_size(client)
        if existing_dim is None:
            _LOGGER.info("Qdrant-Collection '%s' existiert nicht, liefere leere Trefferliste.", self.collection_name)
            return []

        if existing_dim != query_dim:
            raise ValueError(
                "Such-Embedding-Dimension passt nicht zur Qdrant-Collection: "
                f"collection={existing_dim}, query={query_dim}"
            )

        query_filter = None
        if filter_metadata:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_metadata.items()
            ]
            query_filter = Filter(must=conditions)

        results = client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding.tolist(),
            limit=top_k,
            query_filter=query_filter,
        )

        return [
            SearchResult(
                id=r.payload["doc_id"],
                score=r.score,
                metadata=r.payload,
            )
            for r in results
        ]

    def _search_chroma(
        self,
        collection,
        query_embedding: np.ndarray,
        top_k: int,
        filter_metadata: Optional[Dict],
    ) -> List[SearchResult]:
        """Suche in Chroma."""
        results = collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            where=filter_metadata,
        )

        search_results = []

        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                search_results.append(
                    SearchResult(
                        id=doc_id,
                        score=1.0 - results["distances"][0][i],
                        metadata=results["metadatas"][0][i] if results["metadatas"] else {},
                    )
                )

        return search_results

    def find_duplicates(
        self,
        text: str,
        threshold: float = 0.95,
    ) -> List[SearchResult]:
        """
        Findet Duplikate (sehr ähnliche Dokumente).

        Args:
            text: Zu prüfender Text
            threshold: Mindest-Ähnlichkeit (0-1)

        Returns:
            Liste möglicher Duplikate
        """
        results = self.search(text, top_k=10)
        return [r for r in results if r.score >= threshold]


def store_embeddings(text: str, metadata: Dict) -> str:
    """
    Convenience-Funktion zum Speichern von Embeddings.

    Konfigurierbar über ENV:
    - DOCARO_VECTOR_BACKEND
    - DOCARO_VECTOR_COLLECTION
    - DOCARO_EMBEDDING_PROFILE
    - DOCARO_EMBEDDING_MODEL

    Args:
        text: Dokumenten-Text
        metadata: Metadaten (Lieferant, Datum, etc.)

    Returns:
        Dokument-ID
    """
    import uuid

    doc_id = str(uuid.uuid4())

    try:
        from config import Config
        backend = os.getenv("DOCARO_VECTOR_BACKEND", Config.VECTOR_BACKEND)
        collection_name = os.getenv("DOCARO_VECTOR_COLLECTION", Config.VECTOR_COLLECTION)
        embedding_profile = os.getenv("DOCARO_EMBEDDING_PROFILE", Config.EMBEDDING_PROFILE)
        embedding_model = os.getenv("DOCARO_EMBEDDING_MODEL", Config.EMBEDDING_MODEL or "") or None
    except Exception:
        backend = os.getenv("DOCARO_VECTOR_BACKEND", "chroma")
        collection_name = os.getenv("DOCARO_VECTOR_COLLECTION", "docaro_documents")
        embedding_profile = os.getenv("DOCARO_EMBEDDING_PROFILE", "sentence-transformers")
        embedding_model = os.getenv("DOCARO_EMBEDDING_MODEL") or None

    service = VectorService(
        backend=backend,
        collection_name=collection_name,
        embedding_profile=embedding_profile,
        embedding_model=embedding_model,
    )

    service.store_embedding(doc_id, text, metadata)
    return doc_id


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    service = VectorService(backend="chroma")

    doc_id = service.store_embedding(
        doc_id="test_invoice_001",
        text="Rechnung von Testlieferant GmbH vom 15.01.2026 über 1234,56 EUR",
        metadata={
            "supplier": "Testlieferant GmbH",
            "date": "2026-01-15",
            "document_type": "Rechnung",
        },
    )

    print(f"Gespeichert: {doc_id}")

    results = service.search(
        query_text="Rechnung Testlieferant Januar",
        top_k=5,
    )

    print("\nSuchergebnisse:")
    for r in results:
        print(f"  - {r.id}: {r.score:.3f} | {r.metadata}")
