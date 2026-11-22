"""Hybrid and semantic clinical document retrieval engine.

Orchestrates query vectorization, native metadata pre-filtering in ChromaDB,
score conversion, chunk deduplication per patient record, and non-blocking asynchronous execution.
"""

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Union

from fastapi import status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.schemas.search import SearchResponse, SearchResultItem
from app.search.embeddings import EmbeddingGenerator, get_embedding_generator
from app.search.extraction import (
    build_chroma_filters,
    distance_to_score,
    format_timestamp_to_iso,
    parse_datetime_to_timestamp,
)
from app.search.vector_store import VectorStore, get_vector_store

logger = get_logger(__name__)


class SemanticSearchService:
    """High-performance clinical semantic search service with pre-filtering and chunk collapsing."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedding_generator: Optional[EmbeddingGenerator] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_store = vector_store or get_vector_store(self.settings)
        self.embedding_generator = embedding_generator or get_embedding_generator(
            self.settings.EMBEDDING_MODEL
        )

    def _sync_search(
        self,
        query: str,
        resource_type: Optional[str] = None,
        patient_id: Optional[str] = None,
        ts_from: Optional[int] = None,
        ts_to: Optional[int] = None,
        top_k: int = 5,
    ) -> List[SearchResultItem]:
        """Synchronous core search execution: vectorize, pre-filter query, collapse chunks."""
        chroma_filters = build_chroma_filters(
            resource_type=resource_type,
            patient_id=patient_id,
            date_from_ts=ts_from,
            date_to_ts=ts_to,
        )

        query_embedding = self.embedding_generator.generate_single_embedding(query)
        if not query_embedding:
            return []

        fetch_limit = max(top_k * 6, 50)
        raw_matches = self.vector_store.query(
            query_embedding=query_embedding,
            top_k=fetch_limit,
            filters=chroma_filters,
        )

        if not raw_matches:
            return []

        best_records: Dict[str, Dict[str, Any]] = {}
        for match in raw_matches:
            meta = match.get("metadata", {})
            record_id = meta.get("record_id") or match["id"]
            distance = match.get("distance", 1.0)
            score = distance_to_score(distance)

            if record_id not in best_records or score > best_records[record_id]["score"]:
                raw_date = meta.get("date")
                formatted_date = format_timestamp_to_iso(raw_date) if raw_date is not None else format_timestamp_to_iso(datetime.now(timezone.utc))

                snippet = meta.get("snippet") or match.get("document", "")
                if len(snippet) > 300:
                    snippet = snippet[:297] + "..."

                best_records[record_id] = {
                    "record_id": str(record_id),
                    "patient_id": str(meta.get("patient_id", "UNKNOWN")),
                    "resource_type": str(meta.get("resource_type", "Observation")),
                    "source": meta.get("source", "fhir_document"),
                    "date": formatted_date,
                    "score": score,
                    "snippet": snippet,
                }

        sorted_records = sorted(
            best_records.values(), key=lambda r: r["score"], reverse=True
        )[:top_k]

        return [SearchResultItem(**item) for item in sorted_records]

    async def search(
        self,
        query: str,
        resource_type: Optional[str] = None,
        patient_id: Optional[str] = None,
        date_from: Optional[Union[str, datetime]] = None,
        date_to: Optional[Union[str, datetime]] = None,
        top_k: Optional[int] = None,
    ) -> SearchResponse:
        """Asynchronously execute semantic search without blocking the FastAPI event loop.

        Args:
            query: Clinical query string (non-empty).
            resource_type: Optional FHIR resourceType filter (e.g. Observation, Condition).
            patient_id: Optional patient identifier filter (e.g. pat-001).
            date_from: Optional starting datetime/ISO string.
            date_to: Optional ending datetime/ISO string.
            top_k: Number of distinct matches to return (default from settings).

        Returns:
            SearchResponse containing ranked, distinct records and execution metrics.
        """
        start_time = time.perf_counter()
        effective_top_k = top_k if top_k is not None and top_k > 0 else self.settings.SEARCH_TOP_K

        ts_from: Optional[int] = None
        ts_to: Optional[int] = None

        if date_from:
            ts_from = parse_datetime_to_timestamp(date_from)
            if ts_from is None:
                raise AppException(
                    message=f"Invalid date_from format: '{date_from}'. Must be a valid ISO 8601 date.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    error_code="INVALID_DATE_FORMAT",
                )

        if date_to:
            ts_to = parse_datetime_to_timestamp(date_to, is_end_of_day=True)
            if ts_to is None:
                raise AppException(
                    message=f"Invalid date_to format: '{date_to}'. Must be a valid ISO 8601 date.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    error_code="INVALID_DATE_FORMAT",
                )

        if ts_from is not None and ts_to is not None and ts_from > ts_to:
            raise AppException(
                message=f"Invalid date range: date_from ({date_from}) cannot be after date_to ({date_to}).",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                error_code="INVALID_DATE_RANGE",
            )

        results = await run_in_threadpool(
            self._sync_search,
            query=query,
            resource_type=resource_type,
            patient_id=patient_id,
            ts_from=ts_from,
            ts_to=ts_to,
            top_k=effective_top_k,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        logger.info(
            "Semantic search executed: query_len=%d, resource_type=%s, patient_id=%s, date_range=[%s, %s], matches=%d, took=%.2fms",
            len(query),
            resource_type,
            patient_id,
            date_from,
            date_to,
            len(results),
            elapsed_ms,
        )

        return SearchResponse(
            query=query,
            count=len(results),
            took_ms=elapsed_ms,
            results=results,
        )
