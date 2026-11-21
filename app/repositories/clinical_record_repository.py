"""Repository for managing ClinicalRecordModel persistence and paginated retrieval."""

from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import ClinicalRecordModel
from app.repositories.base import BaseRepository


class ClinicalRecordRepository(BaseRepository[ClinicalRecordModel]):
    """Data access repository for clinical records and documents."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ClinicalRecordModel)

    async def create_record(self, record: ClinicalRecordModel) -> ClinicalRecordModel:
        """Persist a single clinical record."""
        self.session.add(record)
        await self.session.flush()
        return record

    async def bulk_create_records(self, records: List[ClinicalRecordModel]) -> None:
        """Bulk insert clinical records."""
        if not records:
            return
        self.session.add_all(records)
        await self.session.flush()

    async def find_by_fingerprint(self, fingerprint: str) -> Optional[ClinicalRecordModel]:
        """Lookup record by its deterministic cryptographic fingerprint."""
        stmt = select(ClinicalRecordModel).where(ClinicalRecordModel.fingerprint == fingerprint)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_fingerprints(self, fingerprints: List[str]) -> List[ClinicalRecordModel]:
        """Lookup records by deterministic cryptographic fingerprints in batch."""
        if not fingerprints:
            return []
        stmt = select(ClinicalRecordModel).where(ClinicalRecordModel.fingerprint.in_(fingerprints))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_records_by_job_id(
        self,
        job_id: str,
        page: int = 1,
        page_size: int = 50,
        status: Optional[str] = None,
    ) -> Tuple[List[ClinicalRecordModel], int]:
        """Retrieve paginated records for a job, optionally filtered by status."""
        conditions = [ClinicalRecordModel.job_id == job_id]
        if status:
            conditions.append(ClinicalRecordModel.status == status.upper())

        count_stmt = select(func.count(ClinicalRecordModel.id)).where(*conditions)
        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar_one()

        offset = (page - 1) * page_size
        query_stmt = (
            select(ClinicalRecordModel)
            .where(*conditions)
            .order_by(ClinicalRecordModel.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.execute(query_stmt)
        items = list(result.scalars().all())

        return items, total
