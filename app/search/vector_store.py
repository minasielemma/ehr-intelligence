"""Persistent vector store abstraction wrapping ChromaDB with cosine distance indexing.

Provides a pluggable interface (VectorRecord and VectorStore) supporting idempotent upsert,
deletion, and metadata-filtered nearest-neighbor queries.
"""

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VectorRecord:
    """Standardized vector record container for database-agnostic storage."""

    id: str
    embedding: List[float]
    document: str
    metadata: Dict[str, Any]


class VectorStore:
    """Vector database adapter wrapping persistent ChromaDB storage."""

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        collection_name: str = "clinical_records",
    ) -> None:
        settings = get_settings()
        self.collection_name = collection_name
        self._lock = threading.Lock()
        self.persist_directory = persist_directory or settings.VECTOR_STORE_PATH

        target_host = host or settings.VECTOR_DB_HOST
        target_port = port or settings.VECTOR_DB_PORT

        if persist_directory is not None:
            path = Path(self.persist_directory).resolve()
            path.mkdir(parents=True, exist_ok=True)
            logger.info("Initializing ChromaDB PersistentClient at [%s]...", str(path))
            self.client = chromadb.PersistentClient(
                path=str(path),
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
        elif target_host and target_host.strip():
            logger.info("Initializing ChromaDB HttpClient connecting to [%s:%d]...", target_host, target_port)
            try:
                self.client = chromadb.HttpClient(
                    host=target_host,
                    port=target_port,
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )
                self.client.heartbeat()
                logger.info("Connected successfully to remote ChromaDB server [%s:%d]", target_host, target_port)
            except Exception as conn_err:
                logger.warning(
                    "Could not connect to ChromaDB server [%s:%d]: %s. Falling back to PersistentClient at [%s].",
                    target_host,
                    target_port,
                    conn_err,
                    self.persist_directory,
                )
                path = Path(self.persist_directory).resolve()
                path.mkdir(parents=True, exist_ok=True)
                self.client = chromadb.PersistentClient(
                    path=str(path),
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )
        else:
            path = Path(self.persist_directory).resolve()
            path.mkdir(parents=True, exist_ok=True)
            logger.info("Initializing ChromaDB PersistentClient at [%s]...", str(path))
            self.client = chromadb.PersistentClient(
                path=str(path),
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )

        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )
        logger.info(
            "ChromaDB collection [%s] ready (existing vectors: %d)",
            self.collection_name,
            self.collection.count(),
        )

    def upsert(self, records: List[VectorRecord], batch_size: int = 100) -> None:
        """Idempotently insert or update vector records in batches."""
        if not records:
            return

        with self._lock:
            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]
                ids = [r.id for r in batch]
                embeddings = [r.embedding for r in batch]
                documents = [r.document for r in batch]
                metadatas = [r.metadata for r in batch]

                self.collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )

    def delete(self, ids: List[str]) -> None:
        """Delete specific vectors by deterministic IDs."""
        if not ids:
            return
        with self._lock:
            try:
                self.collection.delete(ids=ids)
            except Exception as exc:
                logger.warning("Error deleting vectors %s from store: %s", ids, exc)

    def delete_by_record_id(self, record_id: str) -> None:
        """Delete all chunk vectors associated with a specific record_id."""
        if not record_id:
            return
        with self._lock:
            try:
                self.collection.delete(where={"record_id": record_id})
            except Exception as exc:
                logger.warning("Error deleting record [%s] vectors: %s", record_id, exc)

    def delete_by_record_ids(self, record_ids: List[str]) -> None:
        """Delete all chunk vectors associated with multiple record IDs in a single bulk operation."""
        if not record_ids:
            return
        with self._lock:
            try:
                if len(record_ids) == 1:
                    self.collection.delete(where={"record_id": record_ids[0]})
                else:
                    self.collection.delete(where={"record_id": {"$in": list(record_ids)}})
            except Exception as exc:
                logger.warning("Error bulk deleting records %s: %s", record_ids, exc)

    def delete_by_patient_and_source(self, patient_id: str, source: str) -> None:
        """Delete all vectors for a given patient matching a specific source type."""
        if not patient_id:
            return
        with self._lock:
            try:
                self.collection.delete(
                    where={"$and": [{"patient_id": patient_id}, {"source": source}]}
                )
            except Exception as exc:
                logger.warning(
                    "Error deleting vectors for patient [%s] (source=%s): %s",
                    patient_id,
                    source,
                    exc,
                )

    def _refresh_collection(self) -> None:
        """Re-acquire the ChromaDB collection reference in case it was recreated."""
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )
        except Exception as exc:
            logger.warning("Could not refresh ChromaDB collection [%s]: %s", self.collection_name, exc)

    def query(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Query vector database for nearest neighbors using pre-filtering.

        Args:
            query_embedding: L2-normalized float embedding.
            top_k: Number of nearest neighbors to retrieve.
            filters: ChromaDB metadata filter dictionary (e.g. {'$and': [...]}).

        Returns:
            List of matching records with id, metadata, document, and distance.
        """
        effective_k = max(1, top_k)

        query_kwargs: Dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": effective_k,
            "include": ["metadatas", "documents", "distances"],
        }
        if filters:
            query_kwargs["where"] = filters

        try:
            results = self.collection.query(**query_kwargs)
        except Exception as exc:
            if "InvalidCollection" in str(exc):
                self._refresh_collection()
                try:
                    results = self.collection.query(**query_kwargs)
                except Exception as retry_exc:
                    logger.warning("ChromaDB query retry failed after collection refresh: %s", retry_exc)
                    return []
            else:
                logger.warning("ChromaDB query failed with filter %s: %s", filters, exc)
                return []

        matches: List[Dict[str, Any]] = []
        if not results or not results.get("ids") or not results["ids"][0]:
            return matches

        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else []
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
        documents = results.get("documents", [[]])[0] if results.get("documents") else []

        for idx, vec_id in enumerate(ids):
            dist = distances[idx] if idx < len(distances) else 0.0
            meta = metadatas[idx] if idx < len(metadatas) else {}
            doc = documents[idx] if idx < len(documents) else ""
            matches.append(
                {
                    "id": vec_id,
                    "distance": dist,
                    "metadata": meta,
                    "document": doc,
                }
            )

        return matches

    def count(self) -> int:
        """Return total vector count in the collection."""
        try:
            return self.collection.count()
        except Exception as exc:
            if "InvalidCollection" in str(exc):
                self._refresh_collection()
                try:
                    return self.collection.count()
                except Exception:
                    return 0
            return 0

    def reset(self) -> None:
        """Clear all vectors in the collection (useful for testing)."""
        with self._lock:
            try:
                self.client.delete_collection(self.collection_name)
            except Exception:
                pass
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )


_GLOBAL_VECTOR_STORE: Optional[VectorStore] = None
_STORE_LOCK = threading.Lock()


def get_vector_store(
    settings: Optional[Settings] = None,
    persist_directory: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> VectorStore:
    """Retrieve or initialize the global VectorStore singleton."""
    global _GLOBAL_VECTOR_STORE
    if _GLOBAL_VECTOR_STORE is None or persist_directory or host:
        with _STORE_LOCK:
            if persist_directory or host:
                return VectorStore(
                    persist_directory=persist_directory,
                    host=host,
                    port=port,
                )
            if _GLOBAL_VECTOR_STORE is None:
                app_settings = settings or get_settings()
                _GLOBAL_VECTOR_STORE = VectorStore(
                    persist_directory=None,
                    host=app_settings.VECTOR_DB_HOST,
                    port=app_settings.VECTOR_DB_PORT,
                )
    return _GLOBAL_VECTOR_STORE
