"""Repository for persisting, versioning, and querying HL7 FHIR R4 Bundles."""

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.ingestion import FHIRBundleModel, generate_uuid, utc_now
from app.repositories.base import BaseRepository

logger = get_logger(__name__)


def compute_bundle_hash(bundle_data: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of a FHIR Bundle payload.
    
    Strips dynamic envelope metadata (id, timestamp) so identical clinical content
    yields a matching hash for reliable deduplication.
    """
    if not isinstance(bundle_data, dict):
        serialized = json.dumps(bundle_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    content_payload = {k: v for k, v in bundle_data.items() if k not in ("id", "timestamp")}
    serialized = json.dumps(content_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class FHIRBundleRepository(BaseRepository[FHIRBundleModel]):
    """Data access and persistence repository for FHIR R4 Bundles."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session, model_cls=FHIRBundleModel)

    async def get_by_patient_hash(
        self, patient_id: str, content_hash: str
    ) -> Optional[FHIRBundleModel]:
        """Find an existing bundle for a patient with matching content hash."""
        stmt = select(FHIRBundleModel).where(
            FHIRBundleModel.patient_id == patient_id,
            FHIRBundleModel.content_hash == content_hash,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_next_version(self, patient_id: str) -> int:
        """Calculate the next sequential version number for a patient's bundles."""
        ver_stmt = (
            select(func.max(FHIRBundleModel.version))
            .where(FHIRBundleModel.patient_id == patient_id)
        )
        max_ver = (await self.session.execute(ver_stmt)).scalar() or 0
        return max_ver + 1

    async def save_bundle(
        self,
        bundle_id: str,
        patient_id: str,
        patient_mrn: str,
        bundle_type: str,
        bundle_json: Dict[str, Any],
        status: str = "VALID",
        resource_count: Optional[int] = None,
        validation_report_json: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        content_hash: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Tuple[FHIRBundleModel, bool]:
        """Persist a FHIR R4 Bundle with idempotency detection and automatic versioning.

        Returns:
            Tuple of (bundle_model: FHIRBundleModel, is_new: bool)
        """
        c_hash = content_hash or compute_bundle_hash(bundle_json)
        count = resource_count if resource_count is not None else len(bundle_json.get("entry", []))

        existing_dup = await self.get_by_patient_hash(patient_id, c_hash)
        if existing_dup:
            logger.info("Found existing identical FHIR Bundle [%s] for patient [%s]", existing_dup.bundle_id, patient_id)
            return existing_dup, False

        new_version = version if version is not None else await self.get_next_version(patient_id)

        bundle_model = FHIRBundleModel(
            id=generate_uuid(),
            bundle_id=bundle_id,
            patient_id=patient_id,
            patient_mrn=patient_mrn,
            bundle_type=bundle_type,
            version=new_version,
            status=status,
            resource_count=count,
            content_hash=c_hash,
            bundle_json=bundle_json,
            validation_report_json=validation_report_json,
            file_path=file_path,
            metadata_json=metadata_json,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        self.session.add(bundle_model)
        await self.session.flush()
        return bundle_model, True

    async def get_by_bundle_id(self, bundle_id: str) -> Optional[FHIRBundleModel]:
        """Retrieve a bundle by its unique bundle identifier."""
        stmt = select(FHIRBundleModel).where(FHIRBundleModel.bundle_id == bundle_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_patient_id(
        self, patient_id: str, latest_only: bool = True
    ) -> List[FHIRBundleModel]:
        """Retrieve stored bundles for a patient, ordered by version descending."""
        stmt = (
            select(FHIRBundleModel)
            .where(FHIRBundleModel.patient_id == patient_id)
            .order_by(desc(FHIRBundleModel.version))
        )
        if latest_only:
            stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_patient_mrn(
        self, patient_mrn: str, latest_only: bool = True
    ) -> List[FHIRBundleModel]:
        """Retrieve stored bundles by patient MRN."""
        stmt = (
            select(FHIRBundleModel)
            .where(FHIRBundleModel.patient_mrn == patient_mrn)
            .order_by(desc(FHIRBundleModel.version))
        )
        if latest_only:
            stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_bundles(
        self,
        skip: int = 0,
        limit: int = 50,
        status_filter: Optional[str] = None,
    ) -> Tuple[List[FHIRBundleModel], int]:
        """Return paginated list of stored bundles and total count."""
        count_stmt = select(func.count(FHIRBundleModel.id))
        query_stmt = (
            select(FHIRBundleModel)
            .order_by(desc(FHIRBundleModel.created_at))
            .offset(skip)
            .limit(limit)
        )

        if status_filter:
            count_stmt = count_stmt.where(FHIRBundleModel.status == status_filter)
            query_stmt = query_stmt.where(FHIRBundleModel.status == status_filter)

        total_count = (await self.session.execute(count_stmt)).scalar() or 0
        items = (await self.session.execute(query_stmt)).scalars().all()
        return list(items), total_count
