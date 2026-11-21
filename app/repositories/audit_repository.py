"""Repository for appending and retrieving immutable audit log events."""

from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import AuditLogModel
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLogModel]):
    """Data access repository for audit trail logs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLogModel)

    async def append_audit_log(self, log: AuditLogModel) -> None:
        """Persist a single audit log event."""
        self.session.add(log)
        await self.session.flush()

    async def bulk_append_audit_logs(self, logs: List[AuditLogModel]) -> None:
        """Bulk append multiple audit log records."""
        if not logs:
            return
        self.session.add_all(logs)
        await self.session.flush()

    async def get_audit_logs_for_job(self, job_id: str, limit: int = 100) -> List[AuditLogModel]:
        """Fetch audit log records for an ingestion job in chronological order."""
        stmt = (
            select(AuditLogModel)
            .where(AuditLogModel.job_id == job_id)
            .order_by(AuditLogModel.timestamp.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
