"""Repository for persisting, caching, and querying AI-generated clinical summaries."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.summary import ClinicalSummaryModel, generate_uuid, utc_now
from app.repositories.base import BaseRepository

logger = get_logger(__name__)


class ClinicalSummaryRepository(BaseRepository[ClinicalSummaryModel]):
    """Data access and persistence repository for clinical summaries and caching."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session, model_cls=ClinicalSummaryModel)

    async def get_by_cache_key(self, cache_key: str) -> Optional[ClinicalSummaryModel]:
        """Look up a summary by its deterministic SHA-256 cache key."""
        stmt = select(ClinicalSummaryModel).where(ClinicalSummaryModel.cache_key == cache_key)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_latest_by_patient_id(self, patient_id: str) -> Optional[ClinicalSummaryModel]:
        """Retrieve the most recent clinical summary for a given patient."""
        stmt = (
            select(ClinicalSummaryModel)
            .where(ClinicalSummaryModel.patient_id == patient_id)
            .order_by(desc(ClinicalSummaryModel.created_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_patient_id(
        self, patient_id: str, limit: int = 10
    ) -> List[ClinicalSummaryModel]:
        """Retrieve chronological summaries for a patient."""
        stmt = (
            select(ClinicalSummaryModel)
            .where(ClinicalSummaryModel.patient_id == patient_id)
            .order_by(desc(ClinicalSummaryModel.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_patient_and_bundle_hash(
        self, patient_id: str, bundle_hash: str
    ) -> Optional[ClinicalSummaryModel]:
        """Retrieve a summary matching the exact patient ID and source bundle hash."""
        stmt = (
            select(ClinicalSummaryModel)
            .where(
                ClinicalSummaryModel.patient_id == patient_id,
                ClinicalSummaryModel.bundle_hash == bundle_hash,
            )
            .order_by(desc(ClinicalSummaryModel.created_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def save_summary(
        self,
        cache_key: str,
        patient_id: str,
        bundle_hash: str,
        provider: str,
        model_name: str,
        summary_json: Dict[str, Any],
        clinical_summary_text: str,
        word_count: int,
        confidence_level: str = "high",
        bundle_id: Optional[str] = None,
        prompt_version: str = "v1.0.0",
        temperature: float = 0.1,
        status: str = "COMPLETED",
        execution_time_ms: float = 0.0,
        error_message: Optional[str] = None,
        file_path: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ClinicalSummaryModel, bool]:
        """Persist or update a clinical summary record.

        Returns:
            Tuple of (model: ClinicalSummaryModel, is_new: bool)
        """
        existing = await self.get_by_cache_key(cache_key)
        if existing:
            # Update existing cached record with fresh execution details if needed
            existing.summary_json = summary_json
            existing.clinical_summary_text = clinical_summary_text
            existing.word_count = word_count
            existing.confidence_level = confidence_level
            existing.status = status
            existing.execution_time_ms = execution_time_ms
            existing.error_message = error_message
            existing.file_path = file_path or existing.file_path
            existing.metadata_json = metadata_json or existing.metadata_json
            existing.updated_at = utc_now()
            await self.session.flush()
            logger.info("Updated existing cached clinical summary [%s] for patient [%s]", existing.id, patient_id)
            return existing, False

        summary_model = ClinicalSummaryModel(
            id=generate_uuid(),
            cache_key=cache_key,
            patient_id=patient_id,
            bundle_id=bundle_id,
            bundle_hash=bundle_hash,
            provider=provider,
            model_name=model_name,
            prompt_version=prompt_version,
            temperature=temperature,
            status=status,
            summary_json=summary_json,
            clinical_summary_text=clinical_summary_text,
            word_count=word_count,
            confidence_level=confidence_level,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
            file_path=file_path,
            metadata_json=metadata_json,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        self.session.add(summary_model)
        await self.session.flush()
        logger.info(
            "Persisted new clinical summary [%s] (cache_key=%s, words=%d) for patient [%s]",
            summary_model.id,
            cache_key[:12],
            word_count,
            patient_id,
        )
        return summary_model, True

    async def delete_by_patient_id(self, patient_id: str) -> int:
        """Purge all cached summaries for a specific patient.

        Returns:
            Count of deleted records.
        """
        stmt = select(ClinicalSummaryModel).where(ClinicalSummaryModel.patient_id == patient_id)
        results = (await self.session.execute(stmt)).scalars().all()
        count = len(results)
        for item in results:
            await self.session.delete(item)
        if count > 0:
            await self.session.flush()
            logger.info("Invalidated %d cached summaries for patient [%s]", count, patient_id)
        return count

    async def delete_by_cache_key(self, cache_key: str) -> bool:
        """Purge a single cache entry by key."""
        existing = await self.get_by_cache_key(cache_key)
        if existing:
            await self.session.delete(existing)
            await self.session.flush()
            return True
        return False

    async def list_summaries(
        self,
        skip: int = 0,
        limit: int = 50,
        provider: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> Tuple[List[ClinicalSummaryModel], int]:
        """List paginated clinical summaries with optional filtering."""
        count_stmt = select(func.count(ClinicalSummaryModel.id))
        query_stmt = (
            select(ClinicalSummaryModel)
            .order_by(desc(ClinicalSummaryModel.created_at))
            .offset(skip)
            .limit(limit)
        )

        if provider:
            count_stmt = count_stmt.where(ClinicalSummaryModel.provider == provider)
            query_stmt = query_stmt.where(ClinicalSummaryModel.provider == provider)
        if status_filter:
            count_stmt = count_stmt.where(ClinicalSummaryModel.status == status_filter)
            query_stmt = query_stmt.where(ClinicalSummaryModel.status == status_filter)

        total_count = (await self.session.execute(count_stmt)).scalar() or 0
        items = (await self.session.execute(query_stmt)).scalars().all()
        return list(items), total_count
