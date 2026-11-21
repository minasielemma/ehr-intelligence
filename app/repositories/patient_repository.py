"""Repository for managing PatientModel and PatientIdentifierModel persistence."""

from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingestion import PatientIdentifierModel, PatientModel
from app.repositories.base import BaseRepository


class PatientRepository(BaseRepository[PatientModel]):
    """Data access repository for canonical Patient records and identifiers."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PatientModel)

    async def get_patient_with_identifiers(self, patient_id: str) -> Optional[PatientModel]:
        """Fetch patient including their associated external identifiers."""
        stmt = (
            select(PatientModel)
            .options(selectinload(PatientModel.identifiers))
            .where(PatientModel.id == patient_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_scoped_mrn(self, source_system: str, mrn: str) -> List[PatientModel]:
        """Query patients matching an MRN within a specific issuing source system."""
        stmt = (
            select(PatientModel)
            .where(
                func.lower(PatientModel.source_system) == source_system.lower(),
                PatientModel.mrn == mrn,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_scoped_mrns(self, source_system: str, mrns: List[str]) -> List[PatientModel]:
        """Query patients matching any MRN within a specific issuing source system in batch."""
        if not mrns:
            return []
        stmt = (
            select(PatientModel)
            .where(
                func.lower(PatientModel.source_system) == source_system.lower(),
                PatientModel.mrn.in_(mrns),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_demographics(
        self,
        last_name: str,
        first_name: str,
        date_of_birth: Optional[str] = None,
    ) -> List[PatientModel]:
        """Find candidate patients by matching demographic tokens (last name, first initial/name, DOB)."""
        prefix = first_name[:3].lower() if len(first_name) >= 3 else first_name.lower()
        conditions = [
            func.lower(PatientModel.last_name) == last_name.lower(),
            func.lower(PatientModel.first_name).startswith(prefix),
        ]
        if date_of_birth:
            conditions.append(PatientModel.date_of_birth == date_of_birth)

        stmt = select(PatientModel).where(*conditions)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_demographics_batch(
        self,
        last_names: List[str],
    ) -> List[PatientModel]:
        """Find candidate patients by matching any of the provided last names in batch."""
        if not last_names:
            return []
        lower_names = [n.lower() for n in last_names]
        stmt = select(PatientModel).where(func.lower(PatientModel.last_name).in_(lower_names))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_patient(
        self,
        patient: PatientModel,
        identifiers: Optional[List[PatientIdentifierModel]] = None,
    ) -> PatientModel:
        """Persist a new canonical patient and any associated external identifiers."""
        self.session.add(patient)
        if identifiers:
            for ident in identifiers:
                ident.patient_id = patient.id
                self.session.add(ident)
        await self.session.flush()
        return patient

    async def add_identifier(self, identifier: PatientIdentifierModel) -> PatientIdentifierModel:
        """Add an external identifier mapping to an existing patient."""
        self.session.add(identifier)
        await self.session.flush()
        return identifier

    async def search_patients(self, limit: int = 100, offset: int = 0) -> List[PatientModel]:
        """Fetch list of patients with pagination."""
        stmt = select(PatientModel).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_patients(self) -> int:
        """Get total number of canonical patients."""
        stmt = select(func.count(PatientModel.id))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def find_patient_by_identifier(
        self,
        identifier: str,
        source_system: Optional[str] = None,
    ) -> Optional[PatientModel]:
        """Find a canonical patient by MRN, source_patient_id, internal UUID, or external identifier.

        Searches in prioritized order:
        1. Direct match on PatientModel.id (canonical UUID)
        2. Match on PatientModel.mrn or PatientModel.source_patient_id scoped to source_system
        3. Match on PatientModel.mrn or PatientModel.source_patient_id across all systems
        4. Match on external PatientIdentifierModel.value
        """
        if not identifier or not str(identifier).strip():
            return None
        clean_id = str(identifier).replace("Patient/", "").replace("urn:uuid:", "").strip()
        if not clean_id:
            return None

        direct = await self.session.get(PatientModel, clean_id)
        if direct:
            return direct

        if source_system:
            stmt = select(PatientModel).where(
                func.lower(PatientModel.source_system) == source_system.lower(),
                (PatientModel.mrn == clean_id)
                | (PatientModel.source_patient_id == clean_id)
                | (func.lower(PatientModel.mrn) == clean_id.lower())
                | (func.lower(PatientModel.source_patient_id) == clean_id.lower()),
            )
            res = await self.session.execute(stmt)
            pat = res.scalars().first()
            if pat:
                return pat

        stmt = select(PatientModel).where(
            (PatientModel.mrn == clean_id)
            | (PatientModel.source_patient_id == clean_id)
            | (func.lower(PatientModel.mrn) == clean_id.lower())
            | (func.lower(PatientModel.source_patient_id) == clean_id.lower())
        )
        res = await self.session.execute(stmt)
        pat = res.scalars().first()
        if pat:
            return pat

        ident_stmt = (
            select(PatientModel)
            .join(PatientIdentifierModel, PatientIdentifierModel.patient_id == PatientModel.id)
            .where(
                (PatientIdentifierModel.value == clean_id)
                | (func.lower(PatientIdentifierModel.value) == clean_id.lower())
            )
        )
        res = await self.session.execute(ident_stmt)
        pat = res.scalars().first()
        if pat:
            return pat

        return None
