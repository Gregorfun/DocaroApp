"""
Vector-Service für semantische Suche mit Qdrant oder Chroma.

Ermöglicht:
- Speicherung von Dokument-Embeddings
- Semantische Suche ("finde ähnliche Dokumente")
- Duplikaterkennung
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_LOGGER = logging.getLogger(__name__)


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
    """
    
    def __init__(
        self,
        backend: str = "chroma",  # "qdrant" oder "chroma"
        collection_name: str = "docaro_documents",
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    ):
        """
        Args:
            backend: "qdrant" oder "chroma"
            collection_name: Name der Collection
            embedding_model: Huggingface-Modell für Embeddings
        """
        self.backend = backend
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        
        self._client = None
        self._embedding_model = None
    
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
            from qdrant_client.models import Distance, VectorParams
        except ImportError:
            raise ImportError(
                "Qdrant ist nicht installiert. "
                "Installiere mit: pip install qdrant-client"
            )
        
        _LOGGER.info("Verbinde mit Qdrant...")
        
        # Verbinde mit lokalem Qdrant
        client = QdrantClient(host="localhost", port=6333)
        
        # Erstelle Collection falls nicht vorhanden
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if self.collection_name not in collection_names:
            _LOGGER.info(f"Erstelle Qdrant-Collection: {self.collection_name}")
            
            # Embedding-Dimension (abhängig vom Modell)
            embedding_dim = 768  # Standard für mpnet-base
            
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE
                )
            )
        
        return client
    
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
        except:
            _LOGGER.info(f"Erstelle Chroma-Collection: {self.collection_name}")
            collection = client.create_collection(name=self.collection_name)
        
        return collection
    
    def _get_embedding_model(self):
        """Lazy-Loading des Embedding-Modells."""
        if self._embedding_model is not None:
            return self._embedding_model
        
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers ist nicht installiert. "
                "Installiere mit: pip install sentence-transformers"
            )
        
        _LOGGER.info(f"Lade Embedding-Modell: {self.embedding_model_name}")
        self._embedding_model = SentenceTransformer(self.embedding_model_name)
        
        return self._embedding_model
    
    def store_embedding(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
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
        _LOGGER.debug(f"Speichere Embedding für: {doc_id}")
        
        # Generiere Embedding
        model = self._get_embedding_model()
        embedding = model.encode(text)
        
        client = self._get_client()
        
        if self.backend == "qdrant":
            return self._store_qdrant(client, doc_id, embedding, metadata or {})
        elif self.backend == "chroma":
            return self._store_chroma(client, doc_id, embedding, text, metadata or {})
    
    def _store_qdrant(self, client, doc_id: str, embedding: np.ndarray, metadata: Dict):
        """Speichert in Qdrant."""
        from qdrant_client.models import PointStruct
        
        point = PointStruct(
            id=hash(doc_id) % (2**63),  # Qdrant benötigt Integer-IDs
            vector=embedding.tolist(),
            payload={
                'doc_id': doc_id,
                **metadata
            }
        )
        
        client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
        
        return doc_id
    
    def _store_chroma(self, collection, doc_id: str, embedding: np.ndarray, text: str, metadata: Dict):
        """Speichert in Chroma."""
        collection.add(
            ids=[doc_id],
            embeddings=[embedding.tolist()],
            documents=[text[:1000]],  # Chroma speichert auch Text
            metadatas=[metadata]
        )
        
        return doc_id
    
    def search(
        self,
        query_text: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict] = None
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
        _LOGGER.debug(f"Suche: '{query_text[:50]}...'")
        
        # Generiere Query-Embedding
        model = self._get_embedding_model()
        query_embedding = model.encode(query_text)
        
        client = self._get_client()
        
        if self.backend == "qdrant":
            return self._search_qdrant(client, query_embedding, top_k, filter_metadata)
        elif self.backend == "chroma":
            return self._search_chroma(client, query_embedding, top_k, filter_metadata)
    
    def _search_qdrant(
        self,
        client,
        query_embedding: np.ndarray,
        top_k: int,
        filter_metadata: Optional[Dict]
    ) -> List[SearchResult]:
        """Suche in Qdrant."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Filter aufbauen
        query_filter = None
        if filter_metadata:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_metadata.items()
            ]
            query_filter = Filter(must=conditions)
        
        # Suche
        results = client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding.tolist(),
            limit=top_k,
            query_filter=query_filter
        )
        
        return [
            SearchResult(
                id=r.payload['doc_id'],
                score=r.score,
                metadata=r.payload
            )
            for r in results
        ]
    
    def _search_chroma(
        self,
        collection,
        query_embedding: np.ndarray,
        top_k: int,
        filter_metadata: Optional[Dict]
    ) -> List[SearchResult]:
        """Suche in Chroma."""
        results = collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            where=filter_metadata  # Chroma-Filter
        )
        
        # Parse Ergebnisse
        search_results = []
        
        if results['ids'] and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                search_results.append(SearchResult(
                    id=doc_id,
                    score=1.0 - results['distances'][0][i],  # Chroma gibt Distanz
                    metadata=results['metadatas'][0][i] if results['metadatas'] else {}
                ))
        
        return search_results
    
    def find_duplicates(
        self,
        text: str,
        threshold: float = 0.95
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
        
        # Filtere nach Threshold
        duplicates = [r for r in results if r.score >= threshold]
        
        return duplicates


def store_embeddings(text: str, metadata: Dict) -> str:
    """
    Convenience-Funktion zum Speichern von Embeddings.
    
    Args:
        text: Dokumenten-Text
        metadata: Metadaten (Lieferant, Datum, etc.)
    
    Returns:
        Dokument-ID
    """
    import uuid
    
    # Generiere eindeutige ID
    doc_id = str(uuid.uuid4())
    
    # Nutze Chroma als Default (einfacher Setup)
    service = VectorService(backend="chroma")
    
    service.store_embedding(doc_id, text, metadata)
    
    return doc_id


# Beispiel-Nutzung
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialisiere Service
    service = VectorService(backend="chroma")
    
    # Speichere Dokument
    doc_id = service.store_embedding(
        doc_id="test_invoice_001",
        text="Rechnung von Testlieferant GmbH vom 15.01.2026 über 1234,56 EUR",
        metadata={
            'supplier': 'Testlieferant GmbH',
            'date': '2026-01-15',
            'document_type': 'Rechnung'
        }
    )
    
    print(f"✅ Gespeichert: {doc_id}")
    
    # Suche
    results = service.search(
        query_text="Rechnung Testlieferant Januar",
        top_k=5
    )
    
    print(f"\n🔎 Suchergebnisse:")
    for r in results:
        print(f"  - {r.id}: {r.score:.3f} | {r.metadata}")
