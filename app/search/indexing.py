"""Indexing service for extracting, chunking, embedding, and vectorizing EHR data.

Supports individual bundle/summary indexing, asynchronous background worker synchronization,
and batched full database backfill re-indexing.
"""

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.ingestion import FHIRBundleModel
from app.models.summary import ClinicalSummaryModel
from app.search.embeddings import EmbeddingGenerator, get_embedding_generator
from app.search.extraction import (
    chunk_text,
    extract_resource_date,
    extract_searchable_text_from_fhir_resource,
)
from app.search.vector_store import VectorRecord, VectorStore, get_vector_store

logger = get_logger(__name__)


class IndexingService:
    """Service orchestrating document text extraction, chunking, embedding, and vector persistence."""

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

    def index_fhir_bundle_sync(
        self,
        bundle_json: Dict[str, Any],
        patient_id: str,
        bundle_id: str,
        created_at: Optional[datetime] = None,
    ) -> int:
        """Extract all resources in a FHIR Bundle, chunk narratives, embed, and upsert vectors.

        Returns:
            Total number of vector chunks indexed.
        """
        if not isinstance(bundle_json, dict):
            return 0

        entries = bundle_json.get("entry", [])
        if not entries:
            return 0

        fallback_ts = (
            int(created_at.timestamp())
            if created_at
            else int(datetime.now(timezone.utc).timestamp())
        )

        texts_to_embed: List[str] = []
        records_metadata: List[Dict[str, Any]] = []
        deterministic_ids: List[str] = []
        records_to_purge: Set[str] = set()

        for idx, entry in enumerate(entries):
            res = entry.get("resource") if isinstance(entry, dict) else None
            if not isinstance(res, dict):
                continue

            res_type = res.get("resourceType", "Resource")
            raw_rec_id = res.get("id") or f"{bundle_id}_{res_type}_{idx}"
            record_id = str(raw_rec_id)
            records_to_purge.add(record_id)
            res_date_ts = extract_resource_date(res, fallback_timestamp=fallback_ts)

            extracted_text = extract_searchable_text_from_fhir_resource(res)
            if not extracted_text or len(extracted_text.strip()) < 3:
                continue

            chunks = chunk_text(
                extracted_text,
                chunk_size=self.settings.SEARCH_CHUNK_SIZE,
                chunk_overlap=self.settings.SEARCH_CHUNK_OVERLAP,
            )

            for chunk_idx, chunk in enumerate(chunks):
                vec_id = f"{record_id}:fhir_document:{chunk_idx}"
                snippet = chunk[:297] + "..." if len(chunk) > 300 else chunk

                metadata = {
                    "record_id": record_id,
                    "patient_id": patient_id,
                    "resource_type": res_type,
                    "source": "fhir_document",
                    "date": res_date_ts,
                    "snippet": snippet,
                    "chunk_index": chunk_idx,
                }

                texts_to_embed.append(chunk)
                records_metadata.append(metadata)
                deterministic_ids.append(vec_id)

        if not texts_to_embed:
            return 0

        # Cleanly purge prior chunks to avoid orphan vector accumulation
        if records_to_purge:
            self.vector_store.delete_by_record_ids(list(records_to_purge))

        embeddings = self.embedding_generator.generate_embeddings(
            texts_to_embed, batch_size=32
        )

        vector_records = [
            VectorRecord(
                id=deterministic_ids[i],
                embedding=embeddings[i],
                document=texts_to_embed[i],
                metadata=records_metadata[i],
            )
            for i in range(len(texts_to_embed))
        ]

        self.vector_store.upsert(vector_records, batch_size=64)
        logger.debug(
            "Indexed FHIR Bundle [%s] for patient [%s]: %d vector chunks created.",
            bundle_id,
            patient_id,
            len(vector_records),
        )
        return len(vector_records)

    def index_clinical_summary_sync(
        self, summary: Union[ClinicalSummaryModel, Dict[str, Any]]
    ) -> int:
        """Extract AI clinical summary text, chunk, embed, and upsert vectors.

        Supports either a ClinicalSummaryModel OR a decoupled primitive dictionary.

        Returns:
            Total number of vector chunks indexed.
        """
        if isinstance(summary, dict):
            text = summary.get("clinical_summary_text") or ""
            if not text and summary.get("summary_json"):
                parts = []
                s_json = summary["summary_json"]
                if s_json.get("brief_summary"):
                    parts.append(f"Summary: {s_json['brief_summary']}")
                if s_json.get("chief_complaint"):
                    parts.append(f"Chief Complaint: {s_json['chief_complaint']}")
                if s_json.get("assessment_and_plan"):
                    parts.append(f"Assessment: {s_json['assessment_and_plan']}")
                text = " | ".join(parts)

            summary_id = str(summary.get("id", ""))
            patient_id = str(summary.get("patient_id", ""))
            c_at = summary.get("created_at")
            if isinstance(c_at, datetime):
                date_ts = int(c_at.timestamp())
            elif isinstance(c_at, (int, float)):
                date_ts = int(c_at)
            else:
                date_ts = int(datetime.now(timezone.utc).timestamp())
        else:
            text = summary.clinical_summary_text or ""
            if not text and summary.summary_json:
                parts = []
                s_json = summary.summary_json
                if s_json.get("brief_summary"):
                    parts.append(f"Summary: {s_json['brief_summary']}")
                if s_json.get("chief_complaint"):
                    parts.append(f"Chief Complaint: {s_json['chief_complaint']}")
                if s_json.get("assessment_and_plan"):
                    parts.append(f"Assessment: {s_json['assessment_and_plan']}")
                text = " | ".join(parts)

            summary_id = str(summary.id)
            patient_id = str(summary.patient_id)
            date_ts = (
                int(summary.created_at.timestamp())
                if summary.created_at
                else int(datetime.now(timezone.utc).timestamp())
            )

        if not text or len(text.strip()) < 5:
            return 0

        chunks = chunk_text(
            text,
            chunk_size=self.settings.SEARCH_CHUNK_SIZE,
            chunk_overlap=self.settings.SEARCH_CHUNK_OVERLAP,
        )

        texts_to_embed: List[str] = []
        records_metadata: List[Dict[str, Any]] = []
        deterministic_ids: List[str] = []

        for chunk_idx, chunk in enumerate(chunks):
            vec_id = f"{summary_id}:ai_summary:{chunk_idx}"
            snippet = chunk[:297] + "..." if len(chunk) > 300 else chunk

            metadata = {
                "record_id": summary_id,
                "patient_id": patient_id,
                "resource_type": "ClinicalSummary",
                "source": "ai_summary",
                "date": date_ts,
                "snippet": snippet,
                "chunk_index": chunk_idx,
            }

            texts_to_embed.append(chunk)
            records_metadata.append(metadata)
            deterministic_ids.append(vec_id)

        # Purge prior chunks to prevent orphan chunks
        self.vector_store.delete_by_record_id(summary_id)

        embeddings = self.embedding_generator.generate_embeddings(
            texts_to_embed, batch_size=32
        )

        vector_records = [
            VectorRecord(
                id=deterministic_ids[i],
                embedding=embeddings[i],
                document=texts_to_embed[i],
                metadata=records_metadata[i],
            )
            for i in range(len(texts_to_embed))
        ]

        self.vector_store.upsert(vector_records, batch_size=64)
        logger.debug(
            "Indexed Clinical Summary [%s] for patient [%s]: %d vector chunks created.",
            summary_id,
            patient_id,
            len(vector_records),
        )
        return len(vector_records)

    async def index_fhir_bundle(
        self,
        bundle_json: Dict[str, Any],
        patient_id: str,
        bundle_id: str,
        created_at: Optional[datetime] = None,
    ) -> int:
        """Asynchronously index all resources in a FHIR Bundle in a threadpool."""
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(
            self.index_fhir_bundle_sync,
            bundle_json=bundle_json,
            patient_id=patient_id,
            bundle_id=bundle_id,
            created_at=created_at,
        )

    async def index_clinical_summary(
        self, summary: Union[ClinicalSummaryModel, Dict[str, Any]]
    ) -> int:
        """Asynchronously index an AI clinical summary in a threadpool."""
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(
            self.index_clinical_summary_sync,
            summary=summary,
        )

    async def reindex_all(
        self, session: AsyncSession, batch_size: int = 32
    ) -> Dict[str, int]:
        """Backfill all existing FHIR bundles and AI clinical summaries in the database.

        Encodes texts in batches and logs progress.

        Returns:
            Dict containing counts of indexed bundles, summaries, and total vector chunks.
        """
        logger.info("Starting complete vector re-indexing backfill...")
        start_time = time.perf_counter()

        stmt_bundles = select(FHIRBundleModel).order_by(FHIRBundleModel.created_at.asc())
        res_bundles = await session.execute(stmt_bundles)
        bundles = list(res_bundles.scalars().all())
        total_bundles = len(bundles)
        logger.info("Found %d FHIR Bundles to index.", total_bundles)

        total_chunks = 0
        indexed_bundles = 0

        for idx, b in enumerate(bundles, 1):
            try:
                chunks_indexed = await self.index_fhir_bundle(
                    bundle_json=b.bundle_json,
                    patient_id=b.patient_id,
                    bundle_id=b.bundle_id,
                    created_at=b.created_at,
                )
                total_chunks += chunks_indexed
                indexed_bundles += 1
                if idx % 10 == 0 or idx == total_bundles:
                    logger.info(
                        "Indexed FHIR Bundles: %d/%d (total chunks so far: %d)",
                        idx,
                        total_bundles,
                        total_chunks,
                    )
            except Exception as exc:
                logger.error("Failed to index FHIR Bundle [%s]: %s", b.bundle_id, exc)

        stmt_summaries = select(ClinicalSummaryModel).order_by(
            ClinicalSummaryModel.created_at.asc()
        )
        res_summaries = await session.execute(stmt_summaries)
        summaries = list(res_summaries.scalars().all())
        total_summaries = len(summaries)
        logger.info("Found %d Clinical Summaries to index.", total_summaries)

        indexed_summaries = 0
        for idx, s in enumerate(summaries, 1):
            try:
                chunks_indexed = await self.index_clinical_summary(summary=s)
                total_chunks += chunks_indexed
                indexed_summaries += 1
                if idx % 10 == 0 or idx == total_summaries:
                    logger.info(
                        "Indexed Clinical Summaries: %d/%d (total chunks so far: %d)",
                        idx,
                        total_summaries,
                        total_chunks,
                    )
            except Exception as exc:
                logger.error("Failed to index Clinical Summary [%s]: %s", s.id, exc)

        duration = time.perf_counter() - start_time
        logger.info(
            "Vector re-indexing backfill complete in %.2fs: %d bundles, %d summaries, %d vectors.",
            duration,
            indexed_bundles,
            indexed_summaries,
            total_chunks,
        )

        return {
            "bundles": indexed_bundles,
            "summaries": indexed_summaries,
            "total_vectors": total_chunks,
        }


async def sync_index_bundle_background(
    bundle_json: Dict[str, Any],
    patient_id: str,
    bundle_id: str,
    created_at: Optional[datetime] = None,
) -> None:
    """Background task hook to index a newly persisted FHIR bundle without blocking write paths."""
    try:
        service = IndexingService()
        await service.index_fhir_bundle(
            bundle_json=bundle_json,
            patient_id=patient_id,
            bundle_id=bundle_id,
            created_at=created_at,
        )
    except Exception as exc:
        logger.warning("Background FHIR bundle indexing failed for [%s]: %s", bundle_id, exc)


_BACKGROUND_TASKS: Set[asyncio.Task] = set()


def spawn_background_task(coro) -> asyncio.Task:
    """Safely spawn a tracked background task preventing premature garbage collection."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def sync_index_summary_background(
    summary: Union[ClinicalSummaryModel, Dict[str, Any]]
) -> None:
    """Background task hook to index an AI clinical summary without blocking write paths."""
    summary_id = summary.get("id", "UNKNOWN") if isinstance(summary, dict) else getattr(summary, "id", "UNKNOWN")
    try:
        service = IndexingService()
        await service.index_clinical_summary(summary=summary)
    except Exception as exc:
        logger.warning("Background clinical summary indexing failed for [%s]: %s", summary_id, exc)


async def delete_patient_summary_vectors_background(patient_id: str) -> None:
    """Background task hook to purge summary vectors when patient cache is invalidated."""
    try:
        from starlette.concurrency import run_in_threadpool

        vector_store = get_vector_store()
        await run_in_threadpool(
            vector_store.delete_by_patient_and_source,
            patient_id=patient_id,
            source="ai_summary",
        )
    except Exception as exc:
        logger.warning("Background vector purge failed for patient [%s]: %s", patient_id, exc)

