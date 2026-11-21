"""Repository for managing IngestionJobModel persistence and query operations."""

from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import IngestionJobModel
from app.repositories.base import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJobModel]):
    """Data access repository for IngestionJob entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IngestionJobModel)

    async def create_job(self, job: IngestionJobModel) -> IngestionJobModel:
        """Persist a new ingestion job."""
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[IngestionJobModel]:
        """Lookup an existing ingestion job by its idempotency key."""
        stmt = select(IngestionJobModel).where(IngestionJobModel.idempotency_key == idempotency_key)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_job_status(
        self,
        job_id: str,
        status: str,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[IngestionJobModel]:
        """Update job status and timestamps."""
        values: Dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at

        stmt = (
            update(IngestionJobModel)
            .where(IngestionJobModel.id == job_id)
            .values(**values)
            .returning(IngestionJobModel)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_metrics(
        self,
        job_id: str,
        total_records: int,
        successful_records: int,
        rejected_records: int,
        duplicate_records: int,
        warning_records: int,
        conflict_records: int,
    ) -> None:
        """Update aggregate record statistics for a job."""
        stmt = (
            update(IngestionJobModel)
            .where(IngestionJobModel.id == job_id)
            .values(
                total_records=total_records,
                successful_records=successful_records,
                rejected_records=rejected_records,
                duplicate_records=duplicate_records,
                warning_records=warning_records,
                conflict_records=conflict_records,
            )
        )
        await self.session.execute(stmt)
