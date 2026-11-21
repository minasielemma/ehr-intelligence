"""Repository for persisting, querying, and linking multi-domain healthcare records."""

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import (
    AllergyIntoleranceModel,
    CarePlanModel,
    ClaimModel,
    ClinicalRecordModel,
    ConditionModel,
    ConsentModel,
    CoverageModel,
    DiagnosticReportModel,
    DocumentReferenceModel,
    EncounterModel,
    ImagingStudyModel,
    ImmunizationModel,
    MedicationAdministrationModel,
    MedicationRequestModel,
    ObservationModel,
    OrganizationModel,
    PackageFileModel,
    PatientModel,
    PractitionerModel,
    ProcedureModel,
    ProvenanceModel,
    ServiceRequestModel,
)


class DomainRepository:
    """High-performance repository for hospital EHR multi-domain entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_create_organizations(self, items: List[OrganizationModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_practitioners(self, items: List[PractitionerModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_encounters(self, items: List[EncounterModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_conditions(self, items: List[ConditionModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_observations(self, items: List[ObservationModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_medication_requests(self, items: List[MedicationRequestModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_medication_administrations(self, items: List[MedicationAdministrationModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_procedures(self, items: List[ProcedureModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_allergies(self, items: List[AllergyIntoleranceModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_immunizations(self, items: List[ImmunizationModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_coverages(self, items: List[CoverageModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_claims(self, items: List[ClaimModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_care_plans(self, items: List[CarePlanModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_consents(self, items: List[ConsentModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_service_requests(self, items: List[ServiceRequestModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_diagnostic_reports(self, items: List[DiagnosticReportModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_imaging_studies(self, items: List[ImagingStudyModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_document_references(self, items: List[DocumentReferenceModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_provenances(self, items: List[ProvenanceModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def bulk_create_package_files(self, items: List[PackageFileModel]) -> None:
        if items:
            self.session.add_all(items)
            await self.session.flush()

    async def update_package_file(
        self,
        file_id: str,
        status: str,
        total_records: int,
        successful_records: int,
        rejected_records: int,
        error_message: Optional[str] = None,
    ) -> None:
        """Update processing status and counts for a package file."""
        stmt = (
            update(PackageFileModel)
            .where(PackageFileModel.id == file_id)
            .values(
                status=status,
                total_records=total_records,
                successful_records=successful_records,
                rejected_records=rejected_records,
                error_message=error_message,
                completed_at=func.now(),
            )
        )
        await self.session.execute(stmt)

    async def get_package_files_for_job(self, job_id: str) -> List[PackageFileModel]:
        """Fetch all package file processing records for a job."""
        stmt = (
            select(PackageFileModel)
            .where(PackageFileModel.job_id == job_id)
            .order_by(PackageFileModel.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_patient_source_map(self, source_system: Optional[str] = None) -> Dict[str, str]:
        """Map source_patient_id, MRN, and canonical UUID to patient IDs."""
        stmt = select(PatientModel.id, PatientModel.source_patient_id, PatientModel.mrn, PatientModel.source_system)
        if source_system:
            stmt = stmt.where(func.lower(PatientModel.source_system) == source_system.lower())
        result = await self.session.execute(stmt)
        mapping: Dict[str, str] = {}
        for pid, src_id, mrn, s_sys in result.all():
            mapping[pid] = pid
            mapping[f"Patient/{pid}"] = pid
            if src_id:
                mapping[src_id] = pid
                mapping[f"Patient/{src_id}"] = pid
                mapping[src_id.lower()] = pid
                mapping[src_id.upper()] = pid
            if mrn:
                mapping[mrn] = pid
                mapping[f"Patient/{mrn}"] = pid
                mapping[mrn.lower()] = pid
                mapping[mrn.upper()] = pid
        return mapping

    async def get_encounter_source_map(self, source_system: str) -> Dict[str, str]:
        """Map source encounter IDs to canonical encounter UUIDs."""
        stmt = select(EncounterModel.id, EncounterModel.source_id).where(
            func.lower(EncounterModel.source_system) == source_system.lower()
        )
        result = await self.session.execute(stmt)
        return {src_id: enc_id for enc_id, src_id in result.all() if src_id}

    async def get_practitioner_source_map(self, source_system: str) -> Dict[str, str]:
        """Map source practitioner IDs and NPIs to canonical practitioner UUIDs."""
        stmt = select(PractitionerModel.id, PractitionerModel.source_id, PractitionerModel.npi).where(
            func.lower(PractitionerModel.source_system) == source_system.lower()
        )
        result = await self.session.execute(stmt)
        mapping: Dict[str, str] = {}
        for prac_id, src_id, npi in result.all():
            if src_id:
                mapping[src_id] = prac_id
            if npi:
                mapping[npi] = prac_id
        return mapping

    async def get_organization_source_map(self, source_system: str) -> Dict[str, str]:
        """Map source organization IDs to canonical organization UUIDs."""
        stmt = select(OrganizationModel.id, OrganizationModel.source_id).where(
            func.lower(OrganizationModel.source_system) == source_system.lower()
        )
        result = await self.session.execute(stmt)
        return {src_id: org_id for org_id, src_id in result.all() if src_id}

    async def get_coverage_source_map(self, source_system: str) -> Dict[str, str]:
        """Map source coverage IDs to canonical coverage UUIDs."""
        stmt = select(CoverageModel.id, CoverageModel.source_id).where(
            func.lower(CoverageModel.source_system) == source_system.lower()
        )
        result = await self.session.execute(stmt)
        return {src_id: cov_id for cov_id, src_id in result.all() if src_id}

    async def get_medication_request_source_map(self, source_system: str) -> Dict[str, str]:
        """Map source medication request IDs to canonical medication request UUIDs."""
        stmt = select(MedicationRequestModel.id, MedicationRequestModel.source_id).where(
            func.lower(MedicationRequestModel.source_system) == source_system.lower()
        )
        result = await self.session.execute(stmt)
        return {src_id: med_id for med_id, src_id in result.all() if src_id}

    async def get_service_request_source_map(self, source_system: str) -> Dict[str, str]:
        """Map source service request IDs to canonical service request UUIDs."""
        stmt = select(ServiceRequestModel.id, ServiceRequestModel.source_id).where(
            func.lower(ServiceRequestModel.source_system) == source_system.lower()
        )
        result = await self.session.execute(stmt)
        return {src_id: srv_id for srv_id, src_id in result.all() if src_id}


    async def get_domain_counts_for_job(self, job_id: str) -> Dict[str, int]:
        """Retrieve total record counts across all healthcare domains for a specific job."""
        domain_queries = {
            "organizations": select(func.count(OrganizationModel.id)),
            "practitioners": select(func.count(PractitionerModel.id)),
            "encounters": select(func.count(EncounterModel.id)).where(EncounterModel.job_id == job_id),
            "conditions": select(func.count(ConditionModel.id)).where(ConditionModel.job_id == job_id),
            "observations": select(func.count(ObservationModel.id)).where(ObservationModel.job_id == job_id),
            "medication_requests": select(func.count(MedicationRequestModel.id)).where(MedicationRequestModel.job_id == job_id),
            "medication_administrations": select(func.count(MedicationAdministrationModel.id)).where(MedicationAdministrationModel.job_id == job_id),
            "procedures": select(func.count(ProcedureModel.id)).where(ProcedureModel.job_id == job_id),
            "allergies": select(func.count(AllergyIntoleranceModel.id)).where(AllergyIntoleranceModel.job_id == job_id),
            "immunizations": select(func.count(ImmunizationModel.id)).where(ImmunizationModel.job_id == job_id),
            "coverages": select(func.count(CoverageModel.id)).where(CoverageModel.job_id == job_id),
            "claims": select(func.count(ClaimModel.id)).where(ClaimModel.job_id == job_id),
            "care_plans": select(func.count(CarePlanModel.id)).where(CarePlanModel.job_id == job_id),
            "consents": select(func.count(ConsentModel.id)).where(ConsentModel.job_id == job_id),
            "service_requests": select(func.count(ServiceRequestModel.id)).where(ServiceRequestModel.job_id == job_id),
            "diagnostic_reports": select(func.count(DiagnosticReportModel.id)).where(DiagnosticReportModel.job_id == job_id),
            "imaging_studies": select(func.count(ImagingStudyModel.id)).where(ImagingStudyModel.job_id == job_id),
            "document_references": select(func.count(DocumentReferenceModel.id)).where(DocumentReferenceModel.job_id == job_id),
            "provenances": select(func.count(ProvenanceModel.id)).where(ProvenanceModel.job_id == job_id),
            "clinical_records": select(func.count(ClinicalRecordModel.id)).where(ClinicalRecordModel.job_id == job_id),
        }

        counts: Dict[str, int] = {}
        for domain, stmt in domain_queries.items():
            res = await self.session.execute(stmt)
            counts[domain] = res.scalar_one()
        return counts

    async def get_referential_integrity_report(self, job_id: str) -> Dict[str, Any]:
        """Perform comprehensive referential integrity audit on imported records for a job."""
        q_enc_orphan = select(func.count(EncounterModel.id)).where(
            EncounterModel.job_id == job_id,
            EncounterModel.patient_id.is_(None)
        )
        res = await self.session.execute(q_enc_orphan)
        enc_orphans = res.scalar_one()
        q_cond_orphan = select(func.count(ConditionModel.id)).where(
            ConditionModel.job_id == job_id,
            ConditionModel.patient_id.is_(None)
        )
        res = await self.session.execute(q_cond_orphan)
        cond_orphans = res.scalar_one()
        q_obs_orphan = select(func.count(ObservationModel.id)).where(
            ObservationModel.job_id == job_id,
            ObservationModel.patient_id.is_(None)
        )
        res = await self.session.execute(q_obs_orphan)
        obs_orphans = res.scalar_one()
        q_claims_orphan = select(func.count(ClaimModel.id)).where(
            ClaimModel.job_id == job_id,
            ClaimModel.encounter_id.is_(None)
        )
        res = await self.session.execute(q_claims_orphan)
        claim_unlinked_encounters = res.scalar_one()
        domain_counts = await self.get_domain_counts_for_job(job_id)
        total_clinical_records = sum(domain_counts.values())

        return {
            "total_records_evaluated": total_clinical_records,
            "orphan_encounters": enc_orphans,
            "orphan_conditions": cond_orphans,
            "orphan_observations": obs_orphans,
            "unlinked_claims_encounters": claim_unlinked_encounters,
            "referential_integrity_status": "VALID" if (enc_orphans == 0 and cond_orphans == 0 and obs_orphans == 0) else "ANOMALIES_DETECTED",
        }
