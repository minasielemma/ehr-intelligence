"""Ingestion Orchestrator coordinating parsing, cleaning, normalization, identity, deduplication, and persistence.

Supports both single-file EHR ingestion (CSV, JSON, Plain-Text, FHIR R4 Bundles, NDJSON) and
comprehensive multi-file EHR export packages (ZIP, TAR, TGZ) across all 20 healthcare domains.
"""

from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, TextIO, Tuple, Union
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)

from app.core.exceptions import AppException, ValidationException
from app.core.logging import get_logger
from app.ingestion.cleaners.text_cleaner import ClinicalTextCleaner
from app.ingestion.deduplication.fingerprint import RecordFingerprinter
from app.ingestion.normalizers.date_normalizer import DateNormalizer
from app.ingestion.normalizers.demographics import DemographicNormalizer
from app.ingestion.parsers import (
    ExtractedPackageFile,
    PackageManifest,
    PackageProcessor,
    get_parser_for_format,
)
from app.ingestion.reconciliation.patient_matcher import (
    PatientIdentityReconciler,
    ReconciliationDecision,
)
from app.models.ingestion import (
    AllergyIntoleranceModel,
    AuditLogModel,
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
    IngestionJobModel,
    MedicationAdministrationModel,
    MedicationRequestModel,
    ObservationModel,
    OrganizationModel,
    PackageFileModel,
    PatientIdentifierModel,
    PatientModel,
    PractitionerModel,
    ProcedureModel,
    ProvenanceModel,
    ServiceRequestModel,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.clinical_record_repository import ClinicalRecordRepository
from app.repositories.domain_repository import DomainRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.canonical import (
    AuditOutcome,
    AuditRecord,
    CanonicalPatient,
    JobStatus,
    MappingProfile,
    RawRecord,
    ReconciliationStatus,
    RecordStatus,
)
from app.schemas.ingestion import (
    IngestionJobResponse,
    IngestionReportResponse,
    PackageFileResponse,
)

logger = get_logger(__name__)


def generate_uuid() -> str:
    """Generate string UUID4."""
    return str(uuid.uuid4())


class IngestionOrchestrator:
    """Orchestrates end-to-end ingestion lifecycle for EHR clinical records and multi-domain packages."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.job_repo = IngestionJobRepository(session)
        self.patient_repo = PatientRepository(session)
        self.record_repo = ClinicalRecordRepository(session)
        self.audit_repo = AuditRepository(session)
        self.domain_repo = DomainRepository(session)

    async def create_or_get_job(
        self,
        source_format: str,
        source_system: str,
        idempotency_key: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> Tuple[IngestionJobModel, bool]:
        """Create a new IngestionJobModel or retrieve existing if idempotency key matches."""
        if idempotency_key:
            existing_job = await self.job_repo.get_by_idempotency_key(idempotency_key)
            if existing_job:
                if existing_job.status == JobStatus.FAILED.value:
                    logger.info("Found previous failed job [%s] for key [%s], retrying processing", existing_job.id, idempotency_key)
                    return existing_job, True
                logger.info("Found existing job [%s] for idempotency key [%s]", existing_job.id, idempotency_key)
                return existing_job, False

        job = IngestionJobModel(
            id=generate_uuid(),
            idempotency_key=idempotency_key,
            source_format=source_format.lower(),
            source_system=source_system,
            status=JobStatus.RECEIVED.value,
            metadata_json=metadata_json or {},
            created_at=utc_now(),
        )
        created_job = await self.job_repo.create_job(job)
        await self.session.commit()
        return created_job, True

    # =========================================================================
    # Multi-File Package Ingestion Pipeline
    # =========================================================================

    async def process_package(
        self,
        job_id: str,
        archive_path_or_bytes: Union[str, Path, bytes, BinaryIO],
        source_system: str = "hospital_ehr",
        mapping_profile: Optional[MappingProfile] = None,
    ) -> IngestionJobModel:
        """Extract, validate integrity, and process a comprehensive EHR export package (ZIP/TAR)."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise AppException(f"Ingestion job '{job_id}' not found", status_code=404)

        now = utc_now()
        await self.job_repo.update_job_status(job_id, status=JobStatus.PROCESSING.value, started_at=now)
        await self.session.commit()

        temp_dir = Path(tempfile.mkdtemp(prefix=f"ehr_pkg_{job_id}_"))
        mapping = mapping_profile or MappingProfile(source_system=source_system)

        total_records = 0
        successful_records = 0
        rejected_records = 0
        duplicate_records = 0
        warning_records = 0
        conflict_records = 0

        try:
            manifest, extracted_files = PackageProcessor.extract_and_validate(archive_path_or_bytes, temp_dir)
            pkg_models: List[PackageFileModel] = []
            for ef in extracted_files:
                pm = PackageFileModel(
                    id=generate_uuid(),
                    job_id=job_id,
                    file_path=ef.relative_path,
                    domain=ef.domain,
                    format=ef.detected_format,
                    status="PENDING",
                    total_records=0,
                    successful_records=0,
                    rejected_records=0,
                    created_at=utc_now(),
                )
                pkg_models.append(pm)
            await self.domain_repo.bulk_create_package_files(pkg_models)
            await self.session.commit()
            pkg_file_map = {pm.file_path: pm for pm in pkg_models}
            patient_source_map = await self.domain_repo.get_patient_source_map(source_system)
            encounter_source_map = await self.domain_repo.get_encounter_source_map(source_system)
            practitioner_source_map = await self.domain_repo.get_practitioner_source_map(source_system)
            organization_source_map = await self.domain_repo.get_organization_source_map(source_system)
            coverage_source_map = await self.domain_repo.get_coverage_source_map(source_system)
            medication_request_source_map = await self.domain_repo.get_medication_request_source_map(source_system)
            service_request_source_map = await self.domain_repo.get_service_request_source_map(source_system)

            patient_cache: Dict[Tuple[str, str], PatientModel] = {}
            fingerprint_cache: Dict[str, ClinicalRecordModel] = {}
            deferred_references: List[Dict[str, Any]] = []
            domain_buffers: Dict[str, List[Any]] = {
                "organizations": [],
                "practitioners": [],
                "encounters": [],
                "conditions": [],
                "observations": [],
                "medication_requests": [],
                "medication_administrations": [],
                "procedures": [],
                "allergies": [],
                "immunizations": [],
                "coverages": [],
                "claims": [],
                "care_plans": [],
                "consents": [],
                "service_requests": [],
                "diagnostic_reports": [],
                "imaging_studies": [],
                "document_references": [],
                "provenances": [],
                "clinical_records": [],
                "audit_logs": [],
            }
            for ef in extracted_files:
                pm = pkg_file_map.get(ef.relative_path)
                pm_id = pm.id if pm else None
                if pm:
                    pm.status = "PROCESSING"

                file_total = 0
                file_success = 0
                file_rejected = 0

                try:
                    parser = get_parser_for_format(ef.detected_format)
                    with open(ef.absolute_path, "rb") as f_in:
                        raw_stream = parser.parse(f_in, source_system=source_system, mapping_profile=mapping)
                        for raw_rec in raw_stream:
                            file_total += 1
                            total_records += 1

                            rec_domain = ef.domain if (ef.domain and ef.domain not in ["other", "unknown"]) else (raw_rec.metadata.get("domain") or ef.domain)
                            is_pat_domain = rec_domain in ["patients", "demographics"]

                            if is_pat_domain:
                                (
                                    clin_rec,
                                    audits,
                                    succ,
                                    rej,
                                    dup,
                                    warn,
                                    conf,
                                ) = await self._process_single_record(
                                    job_id=job_id,
                                    raw_rec=raw_rec,
                                    source_system=source_system,
                                    mapping=mapping,
                                    patient_cache=patient_cache,
                                    fingerprint_cache=fingerprint_cache,
                                )
                                if clin_rec:
                                    domain_buffers["clinical_records"].append(clin_rec)
                                    if clin_rec.patient_id:
                                        p_raw = raw_rec.raw_patient or {}
                                        for k in ["mrn", "patient_id", "source_patient_id", "id"]:
                                            val = p_raw.get(k)
                                            if val:
                                                patient_source_map[str(val)] = clin_rec.patient_id
                                                patient_source_map[str(val).replace("Patient/", "").strip()] = clin_rec.patient_id
                                        pref = self.extract_patient_reference(p_raw, raw_rec)
                                        if pref:
                                            patient_source_map[pref] = clin_rec.patient_id
                                            patient_source_map[pref.upper()] = clin_rec.patient_id
                                            patient_source_map[pref.lower()] = clin_rec.patient_id
                                        if raw_rec.source_record_id:
                                            patient_source_map[str(raw_rec.source_record_id)] = clin_rec.patient_id
                                            patient_source_map[str(raw_rec.source_record_id).replace("Patient/", "").strip()] = clin_rec.patient_id
                                if audits:
                                    domain_buffers["audit_logs"].extend(audits)

                                if succ:
                                    successful_records += 1
                                    file_success += 1
                                if rej:
                                    rejected_records += 1
                                    file_rejected += 1
                                if dup:
                                    duplicate_records += 1
                                if warn:
                                    warning_records += 1
                                if conf:
                                    conflict_records += 1
                            else:
                                entity_data = (
                                    raw_rec.metadata.get("entity")
                                    or raw_rec.metadata.get("raw_row")
                                    or (raw_rec.raw_document if isinstance(raw_rec.raw_document, dict) else {})
                                )
                                await self._dispatch_domain_entity(
                                    domain=rec_domain,
                                    raw_data=entity_data,
                                    raw_rec=raw_rec,
                                    job_id=job_id,
                                    source_system=source_system,
                                    patient_source_map=patient_source_map,
                                    encounter_source_map=encounter_source_map,
                                    practitioner_source_map=practitioner_source_map,
                                    organization_source_map=organization_source_map,
                                    coverage_source_map=coverage_source_map,
                                    medication_request_source_map=medication_request_source_map,
                                    service_request_source_map=service_request_source_map,
                                    domain_buffers=domain_buffers,
                                    deferred_references=deferred_references,
                                )
                                file_success += 1
                                successful_records += 1

                            await self._flush_domain_buffers(domain_buffers, threshold=100)

                    await self._flush_domain_buffers(domain_buffers, threshold=0)

                    if pm_id:
                        await self.domain_repo.update_package_file(
                            file_id=pm_id,
                            status="COMPLETED",
                            total_records=file_total,
                            successful_records=file_success,
                            rejected_records=file_rejected,
                        )
                        await self.session.commit()

                except Exception as file_exc:
                    logger.warning("Error processing package file [%s]: %s", ef.relative_path, file_exc)
                    await self.session.rollback()
                    if pm_id:
                        try:
                            await self.domain_repo.update_package_file(
                                file_id=pm_id,
                                status="FAILED",
                                total_records=file_total,
                                successful_records=file_success,
                                rejected_records=file_rejected,
                                error_message=str(file_exc),
                            )
                            await self.session.commit()
                        except Exception:
                            pass
            await self._flush_domain_buffers(domain_buffers, threshold=0)
            await self._resolve_deferred_references(
                deferred_references=deferred_references,
                patient_source_map=patient_source_map,
                encounter_source_map=encounter_source_map,
                coverage_source_map=coverage_source_map,
                practitioner_source_map=practitioner_source_map,
                organization_source_map=organization_source_map,
                medication_request_source_map=medication_request_source_map,
                service_request_source_map=service_request_source_map,
            )
            if rejected_records > 0 or warning_records > 0 or conflict_records > 0:
                final_status = JobStatus.COMPLETED_WITH_WARNINGS.value
            else:
                final_status = JobStatus.COMPLETED.value

            completed_at = utc_now()
            await self.job_repo.update_job_status(job_id, status=final_status, completed_at=completed_at)
            await self.job_repo.update_metrics(
                job_id=job_id,
                total_records=total_records,
                successful_records=successful_records,
                rejected_records=rejected_records,
                duplicate_records=duplicate_records,
                warning_records=warning_records,
                conflict_records=conflict_records,
            )
            await self.session.commit()

        except Exception as exc:
            logger.exception("Package ingestion failed for job [%s]", job_id)
            await self.session.rollback()
            completed_at = utc_now()
            await self.job_repo.update_job_status(
                job_id,
                status=JobStatus.FAILED.value,
                error_message=str(exc),
                completed_at=completed_at,
            )
            await self.session.commit()
            raise
        finally:
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

        updated_job = await self.job_repo.get_by_id(job_id)
        return updated_job or job

    # =========================================================================
    # Single-File Ingestion Pipeline
    # =========================================================================

    async def process_ingestion(
        self,
        job_id: str,
        stream_or_data: Union[str, bytes, TextIO, BinaryIO],
        source_format: str,
        source_system: str,
        mapping_profile: Optional[MappingProfile] = None,
    ) -> IngestionJobModel:
        """Execute end-to-end processing pipeline for a single uploaded EHR file."""
        norm_fmt = source_format.lower().lstrip(".")
        if norm_fmt in ["zip", "tar", "gz", "tgz"]:
            return await self.process_package(
                job_id=job_id,
                archive_path_or_bytes=stream_or_data,
                source_system=source_system,
                mapping_profile=mapping_profile,
            )

        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise AppException(f"Ingestion job '{job_id}' not found", status_code=404)

        now = utc_now()
        await self.job_repo.update_job_status(job_id, status=JobStatus.PROCESSING.value, started_at=now)
        await self.session.commit()

        parser = get_parser_for_format(source_format)
        mapping = mapping_profile or MappingProfile(source_system=source_system)

        total_records = 0
        successful_records = 0
        rejected_records = 0
        duplicate_records = 0
        warning_records = 0
        conflict_records = 0

        patient_cache: Dict[Tuple[str, str], PatientModel] = {}
        fingerprint_cache: Dict[str, ClinicalRecordModel] = {}

        patient_source_map = await self.domain_repo.get_patient_source_map(source_system)
        encounter_source_map = await self.domain_repo.get_encounter_source_map(source_system)
        practitioner_source_map = await self.domain_repo.get_practitioner_source_map(source_system)
        organization_source_map = await self.domain_repo.get_organization_source_map(source_system)
        coverage_source_map = await self.domain_repo.get_coverage_source_map(source_system)
        medication_request_source_map = await self.domain_repo.get_medication_request_source_map(source_system)
        service_request_source_map = await self.domain_repo.get_service_request_source_map(source_system)

        domain_buffers: Dict[str, List[Any]] = {
            "organizations": [],
            "practitioners": [],
            "encounters": [],
            "conditions": [],
            "observations": [],
            "medication_requests": [],
            "medication_administrations": [],
            "procedures": [],
            "allergies": [],
            "immunizations": [],
            "coverages": [],
            "claims": [],
            "care_plans": [],
            "consents": [],
            "service_requests": [],
            "diagnostic_reports": [],
            "imaging_studies": [],
            "document_references": [],
            "provenances": [],
            "clinical_records": [],
            "audit_logs": [],
        }
        deferred_references: List[Dict[str, Any]] = []

        try:
            raw_records = parser.parse(stream_or_data, source_system=source_system, mapping_profile=mapping)

            for raw_rec in raw_records:
                total_records += 1
                rec_domain = raw_rec.metadata.get("domain")

                if rec_domain and rec_domain not in ["patients", "demographics"]:
                    entity_data = (
                        raw_rec.metadata.get("entity")
                        or raw_rec.metadata.get("raw_row")
                        or (raw_rec.raw_document if isinstance(raw_rec.raw_document, dict) else {})
                    )
                    await self._dispatch_domain_entity(
                        domain=rec_domain,
                        raw_data=entity_data,
                        raw_rec=raw_rec,
                        job_id=job_id,
                        source_system=source_system,
                        patient_source_map=patient_source_map,
                        encounter_source_map=encounter_source_map,
                        practitioner_source_map=practitioner_source_map,
                        organization_source_map=organization_source_map,
                        coverage_source_map=coverage_source_map,
                        medication_request_source_map=medication_request_source_map,
                        service_request_source_map=service_request_source_map,
                        domain_buffers=domain_buffers,
                        deferred_references=deferred_references,
                    )
                    successful_records += 1
                else:
                    (
                        clin_rec,
                        audit_logs,
                        is_success,
                        is_rejected,
                        is_dup,
                        is_warn,
                        is_conflict,
                    ) = await self._process_single_record(
                        job_id=job_id,
                        raw_rec=raw_rec,
                        source_system=source_system,
                        mapping=mapping,
                        patient_cache=patient_cache,
                        fingerprint_cache=fingerprint_cache,
                    )

                    if clin_rec:
                        domain_buffers["clinical_records"].append(clin_rec)
                        if clin_rec.patient_id:
                            p_raw = raw_rec.raw_patient or {}
                            for k in ["mrn", "patient_id", "source_patient_id", "id"]:
                                val = p_raw.get(k)
                                if val:
                                    patient_source_map[str(val)] = clin_rec.patient_id
                                    patient_source_map[str(val).replace("Patient/", "").strip()] = clin_rec.patient_id
                            pref = self.extract_patient_reference(p_raw, raw_rec)
                            if pref:
                                patient_source_map[pref] = clin_rec.patient_id
                                patient_source_map[pref.upper()] = clin_rec.patient_id
                                patient_source_map[pref.lower()] = clin_rec.patient_id
                            if raw_rec.source_record_id:
                                patient_source_map[str(raw_rec.source_record_id)] = clin_rec.patient_id
                                patient_source_map[str(raw_rec.source_record_id).replace("Patient/", "").strip()] = clin_rec.patient_id

                    if audit_logs:
                        domain_buffers["audit_logs"].extend(audit_logs)

                    if is_success:
                        successful_records += 1
                    if is_rejected:
                        rejected_records += 1
                    if is_dup:
                        duplicate_records += 1
                    if is_warn:
                        warning_records += 1
                    if is_conflict:
                        conflict_records += 1

                await self._flush_domain_buffers(domain_buffers, threshold=100)

            await self._flush_domain_buffers(domain_buffers, threshold=0)
            await self._resolve_deferred_references(
                deferred_references=deferred_references,
                patient_source_map=patient_source_map,
                encounter_source_map=encounter_source_map,
                coverage_source_map=coverage_source_map,
                practitioner_source_map=practitioner_source_map,
                organization_source_map=organization_source_map,
                medication_request_source_map=medication_request_source_map,
                service_request_source_map=service_request_source_map,
            )

            if rejected_records > 0 or warning_records > 0 or conflict_records > 0:
                final_status = JobStatus.COMPLETED_WITH_WARNINGS.value
            else:
                final_status = JobStatus.COMPLETED.value

            completed_at = utc_now()
            await self.job_repo.update_job_status(job_id, status=final_status, completed_at=completed_at)
            await self.job_repo.update_metrics(
                job_id=job_id,
                total_records=total_records,
                successful_records=successful_records,
                rejected_records=rejected_records,
                duplicate_records=duplicate_records,
                warning_records=warning_records,
                conflict_records=conflict_records,
            )
            await self.session.commit()

        except Exception as exc:
            logger.exception("Ingestion failed for job [%s]", job_id)
            await self.session.rollback()
            completed_at = utc_now()
            await self.job_repo.update_job_status(
                job_id,
                status=JobStatus.FAILED.value,
                error_message=str(exc),
                completed_at=completed_at,
            )
            await self.session.commit()
            raise

        updated_job = await self.job_repo.get_by_id(job_id)
        return updated_job or job

    # =========================================================================
    # Entity Dispatching & Referential Integrity Helpers
    # =========================================================================

    @classmethod
    def extract_patient_reference(
        cls,
        raw_data: Optional[Dict[str, Any]] = None,
        raw_rec: Optional[RawRecord] = None,
    ) -> Optional[str]:
        """Extract patient identifier (MRN, patient_id, subject reference) from any data structure or domain record."""
        candidates: List[Any] = []

        if raw_data and isinstance(raw_data, dict):
            target_type = str(raw_data.get("target_resource_type") or "").strip().lower()
            if target_type == "patient":
                candidates.append(raw_data.get("target_resource_id"))

            for key in [
                "patient_source_id",
                "patient_id",
                "patient_mrn",
                "mrn",
                "medical_record_number",
                "source_patient_id",
                "pat_id",
                "pat_mrn",
                "subject_id",
                "subject",
                "patient",
                "patient_ref",
                "patient_reference",
                "beneficiary_id",
                "beneficiary",
                "grantor",
                "member_id",
            ]:
                if key in raw_data and raw_data[key] is not None:
                    candidates.append(raw_data[key])

        if raw_rec:
            p_raw = raw_rec.raw_patient
            if isinstance(p_raw, dict):
                for key in [
                    "mrn",
                    "patient_id",
                    "source_patient_id",
                    "patient_mrn",
                    "medical_record_number",
                    "id",
                    "pat_id",
                    "pat_mrn",
                ]:
                    if key in p_raw and p_raw[key] is not None:
                        candidates.append(p_raw[key])

            meta = raw_rec.metadata
            if isinstance(meta, dict):
                for key in [
                    "patient_id",
                    "patient_mrn",
                    "mrn",
                    "source_patient_id",
                    "patient_source_id",
                    "subject",
                    "patient",
                ]:
                    if key in meta and meta[key] is not None:
                        candidates.append(meta[key])

        for val in candidates:
            if val is None:
                continue
            if isinstance(val, dict):
                ref = val.get("reference") or val.get("id") or val.get("value")
                if ref:
                    cleaned = (
                        str(ref)
                        .replace("Patient/", "")
                        .replace("urn:uuid:", "")
                        .replace("#", "")
                        .strip()
                    )
                    if cleaned and cleaned.lower() not in ["none", "null", ""]:
                        return cleaned
            else:
                s_val = str(val).strip()
                if s_val and s_val.lower() not in ["none", "null", ""]:
                    cleaned = (
                        s_val
                        .replace("Patient/", "")
                        .replace("urn:uuid:", "")
                        .replace("#", "")
                        .strip()
                    )
                    if cleaned and cleaned.lower() not in ["none", "null", ""]:
                        return cleaned

        return None

    async def _dispatch_domain_entity(
        self,
        domain: str,
        raw_data: Dict[str, Any],
        raw_rec: RawRecord,
        job_id: str,
        source_system: str,
        patient_source_map: Dict[str, str],
        encounter_source_map: Dict[str, str],
        practitioner_source_map: Dict[str, str],
        organization_source_map: Dict[str, str],
        coverage_source_map: Dict[str, str],
        medication_request_source_map: Dict[str, str],
        service_request_source_map: Dict[str, str],
        domain_buffers: Dict[str, List[Any]],
        deferred_references: List[Dict[str, Any]],
    ) -> None:
        """Instantiate domain entity model, perform FK resolution, and stage into buffers."""
        norm_domain = domain.lower().replace("-", "_").strip()
        domain_singular = norm_domain.rstrip("s")
        source_id = str(
            raw_data.get("id")
            or raw_data.get(f"{domain_singular}_id")
            or raw_data.get("provenance_id")
            or raw_rec.source_record_id
            or generate_uuid()
        )

        # Resolve referenced IDs
        patient_ref = self.extract_patient_reference(raw_data, raw_rec)

        enc_ref = str(
            raw_rec.metadata.get("encounter_source_id")
            or raw_data.get("encounter_source_id")
            or raw_data.get("encounter_id")
            or ""
        ).replace("Encounter/", "").strip()

        prac_ref = str(
            raw_data.get("practitioner_source_id")
            or raw_data.get("practitioner_id")
            or ""
        ).replace("Practitioner/", "").strip()

        org_ref = str(
            raw_data.get("organization_source_id")
            or raw_data.get("organization_id")
            or ""
        ).replace("Organization/", "").strip()

        cov_ref = str(
            raw_data.get("coverage_source_id")
            or raw_data.get("coverage_id")
            or ""
        ).replace("Coverage/", "").strip()

        med_req_ref = str(
            raw_data.get("medication_request_source_id")
            or raw_data.get("medication_request_id")
            or ""
        ).replace("MedicationRequest/", "").strip()

        srv_req_ref = str(
            raw_data.get("service_request_source_id")
            or raw_data.get("service_request_id")
            or ""
        ).replace("ServiceRequest/", "").strip()

        patient_uuid: Optional[str] = None
        if patient_ref:
            patient_uuid = (
                patient_source_map.get(patient_ref)
                or patient_source_map.get(patient_ref.upper())
                or patient_source_map.get(patient_ref.lower())
            )

        # Query database across all patient identifiers if not in current source map
        if not patient_uuid and patient_ref:
            existing_patient = await self.patient_repo.find_patient_by_identifier(
                patient_ref, source_system=source_system
            )
            if existing_patient:
                patient_uuid = existing_patient.id
                patient_source_map[patient_ref] = patient_uuid
                patient_source_map[patient_ref.upper()] = patient_uuid
                patient_source_map[patient_ref.lower()] = patient_uuid
                if existing_patient.mrn:
                    patient_source_map[existing_patient.mrn] = patient_uuid
                    patient_source_map[existing_patient.mrn.upper()] = patient_uuid
                if existing_patient.source_patient_id:
                    patient_source_map[existing_patient.source_patient_id] = patient_uuid

        # Create placeholder patient for unresolved references in patient-associated domains
        if not patient_uuid and norm_domain not in ["organizations", "facilities", "practitioners", "providers"]:
            mrn_val = patient_ref or f"UNKNOWN_{job_id[:8]}"
            placeholder_patient = PatientModel(
                id=generate_uuid(),
                source_system=source_system,
                source_patient_id=mrn_val,
                mrn=mrn_val,
                first_name="UNRESOLVED",
                last_name="PATIENT",
                reconciliation_status=ReconciliationStatus.MANUAL_REVIEW_REQUIRED.value,
                confidence_score=0.0,
            )
            self.session.add(placeholder_patient)
            patient_uuid = placeholder_patient.id
            if patient_ref:
                patient_source_map[patient_ref] = patient_uuid
                patient_source_map[patient_ref.upper()] = patient_uuid
                patient_source_map[patient_ref.lower()] = patient_uuid

        enc_uuid = encounter_source_map.get(enc_ref)
        prac_uuid = practitioner_source_map.get(prac_ref)
        org_uuid = organization_source_map.get(org_ref)
        cov_uuid = coverage_source_map.get(cov_ref)
        med_req_uuid = medication_request_source_map.get(med_req_ref)
        srv_req_uuid = service_request_source_map.get(srv_req_ref)

        created_entity: Optional[Any] = None

        if norm_domain in ["organizations", "facilities"]:
            created_entity = OrganizationModel(
                id=generate_uuid(),
                source_system=source_system,
                source_id=source_id,
                name=str(raw_data.get("name") or "Healthcare Facility"),
                org_type=raw_data.get("type") or raw_data.get("org_type"),
                phone=raw_data.get("phone"),
                active=bool(raw_data.get("active", True)),
                created_at=utc_now(),
            )
            organization_source_map[source_id] = created_entity.id
            if source_id.startswith("Organization/"):
                organization_source_map[source_id.replace("Organization/", "")] = created_entity.id
            domain_buffers["organizations"].append(created_entity)

        elif norm_domain in ["practitioners", "providers"]:
            created_entity = PractitionerModel(
                id=generate_uuid(),
                source_system=source_system,
                source_id=source_id,
                npi=raw_data.get("npi"),
                first_name=str(raw_data.get("first_name") or "UNKNOWN"),
                last_name=str(raw_data.get("last_name") or "UNKNOWN"),
                specialty=raw_data.get("specialty"),
                email=raw_data.get("email"),
                active=bool(raw_data.get("active", True)),
                created_at=utc_now(),
            )
            practitioner_source_map[source_id] = created_entity.id
            if source_id.startswith("Practitioner/"):
                practitioner_source_map[source_id.replace("Practitioner/", "")] = created_entity.id
            if raw_data.get("npi"):
                practitioner_source_map[raw_data["npi"]] = created_entity.id
            domain_buffers["practitioners"].append(created_entity)

        elif norm_domain in ["encounters", "visits"]:
            created_entity = EncounterModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                practitioner_id=prac_uuid,
                organization_id=org_uuid,
                status=str(raw_data.get("status") or "finished"),
                encounter_class=str(raw_data.get("encounter_class") or raw_data.get("class_code") or raw_data.get("class") or "outpatient"),
                encounter_type=raw_data.get("encounter_type") or raw_data.get("type"),
                start_date=raw_data.get("start_date") or raw_data.get("start_time") or raw_data.get("date"),
                end_date=raw_data.get("end_date") or raw_data.get("end_time"),
                reason_code=raw_data.get("reason_code"),
                reason_display=raw_data.get("reason_display"),
                service_provider=raw_data.get("service_provider"),
                created_at=utc_now(),
            )
            encounter_source_map[source_id] = created_entity.id
            if source_id.startswith("Encounter/"):
                encounter_source_map[source_id.replace("Encounter/", "")] = created_entity.id
            if raw_rec.source_record_id:
                encounter_source_map[str(raw_rec.source_record_id)] = created_entity.id
            domain_buffers["encounters"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

        elif norm_domain in ["conditions", "diagnoses"]:
            created_entity = ConditionModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                code=str(raw_data.get("code") or "UNKNOWN"),
                code_system=str(raw_data.get("code_system") or raw_data.get("system") or "http://hl7.org/fhir/sid/icd-10-cm"),
                display=str(raw_data.get("display") or raw_data.get("description") or "Condition"),
                clinical_status=str(raw_data.get("clinical_status") or "active"),
                verification_status=str(raw_data.get("verification_status") or "confirmed"),
                severity=raw_data.get("severity"),
                onset_date=raw_data.get("onset_date") or raw_data.get("onset"),
                recorded_date=raw_data.get("recorded_date"),
                created_at=utc_now(),
            )
            domain_buffers["conditions"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["observations", "vitals", "labs"]:
            val_qty = None
            if raw_data.get("value_quantity") is not None or raw_data.get("value_numeric") is not None:
                try:
                    val_qty = float(raw_data.get("value_numeric", raw_data.get("value_quantity")))
                except Exception:
                    val_qty = None

            ref_low = None
            if raw_data.get("reference_range_low") is not None:
                try:
                    ref_low = float(raw_data["reference_range_low"])
                except Exception:
                    ref_low = None

            ref_high = None
            if raw_data.get("reference_range_high") is not None:
                try:
                    ref_high = float(raw_data["reference_range_high"])
                except Exception:
                    ref_high = None

            created_entity = ObservationModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                category=str(raw_data.get("category") or "vital-signs"),
                code=str(raw_data.get("code") or "UNKNOWN"),
                code_system=str(raw_data.get("code_system") or raw_data.get("system") or "http://loinc.org"),
                display=str(raw_data.get("display") or raw_data.get("name") or "Observation"),
                value_numeric=val_qty,
                value_string=str(raw_data.get("value_string") or raw_data.get("value") or ""),
                unit=raw_data.get("unit") or raw_data.get("value_unit"),
                reference_range_low=ref_low,
                reference_range_high=ref_high,
                interpretation=raw_data.get("interpretation"),
                status=str(raw_data.get("status") or "final"),
                effective_date=raw_data.get("effective_date") or raw_data.get("date"),
                created_at=utc_now(),
            )
            domain_buffers["observations"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["medication_requests", "medications", "prescriptions"]:
            dose_qty = None
            if raw_data.get("dose_quantity") is not None:
                try:
                    dose_qty = float(raw_data["dose_quantity"])
                except Exception:
                    dose_qty = None

            created_entity = MedicationRequestModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                practitioner_id=prac_uuid,
                code=str(raw_data.get("code") or "UNKNOWN"),
                code_system=str(raw_data.get("code_system") or raw_data.get("system") or "http://www.nlm.nih.gov/research/umls/rxnorm"),
                display=str(raw_data.get("display") or raw_data.get("medication") or "Medication"),
                status=str(raw_data.get("status") or "active"),
                intent=str(raw_data.get("intent") or "order"),
                dosage_instruction=raw_data.get("dosage_instruction") or raw_data.get("dosage"),
                route=raw_data.get("route"),
                dose_quantity=dose_qty,
                dose_unit=raw_data.get("dose_unit") or raw_data.get("unit"),
                frequency=raw_data.get("frequency"),
                authored_on=raw_data.get("authored_on") or raw_data.get("date"),
                created_at=utc_now(),
            )
            medication_request_source_map[source_id] = created_entity.id
            if source_id.startswith("MedicationRequest/"):
                medication_request_source_map[source_id.replace("MedicationRequest/", "")] = created_entity.id
            domain_buffers["medication_requests"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["medication_administrations", "administrations"]:
            dose_adm = None
            if raw_data.get("dosage_administered") is not None:
                try:
                    dose_adm = float(raw_data["dosage_administered"])
                except Exception:
                    dose_adm = None

            created_entity = MedicationAdministrationModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                medication_request_id=med_req_uuid,
                code=str(raw_data.get("code") or "UNKNOWN"),
                display=str(raw_data.get("display") or "Medication Administration"),
                status=str(raw_data.get("status") or "completed"),
                dosage_administered=dose_adm,
                unit=raw_data.get("unit") or raw_data.get("dose_unit"),
                route=raw_data.get("route"),
                effective_date=raw_data.get("effective_date") or raw_data.get("date") or raw_data.get("effective_time"),
                created_at=utc_now(),
            )
            domain_buffers["medication_administrations"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})
            if not med_req_uuid and med_req_ref:
                deferred_references.append({"entity": created_entity, "attr": "medication_request_id", "source_id": med_req_ref, "type": "medication_request"})

        elif norm_domain in ["procedures", "surgeries"]:
            created_entity = ProcedureModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                code=str(raw_data.get("code") or "UNKNOWN"),
                code_system=str(raw_data.get("code_system") or raw_data.get("system") or "http://snomed.info/sct"),
                display=str(raw_data.get("display") or "Procedure"),
                status=str(raw_data.get("status") or "completed"),
                performed_date=raw_data.get("performed_date") or raw_data.get("date"),
                created_at=utc_now(),
            )
            domain_buffers["procedures"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["allergies", "allergy_intolerances"]:
            created_entity = AllergyIntoleranceModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                clinical_status=str(raw_data.get("clinical_status") or "active"),
                verification_status=str(raw_data.get("verification_status") or "confirmed"),
                allergy_type=raw_data.get("allergy_type") or raw_data.get("type"),
                category=raw_data.get("category"),
                criticality=raw_data.get("criticality"),
                code=str(raw_data.get("code") or "UNKNOWN"),
                display=str(raw_data.get("display") or "Allergy"),
                recorded_date=raw_data.get("recorded_date") or raw_data.get("date"),
                created_at=utc_now(),
            )
            domain_buffers["allergies"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

        elif norm_domain in ["immunizations", "vaccines"]:
            created_entity = ImmunizationModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                status=str(raw_data.get("status") or "completed"),
                vaccine_code=str(raw_data.get("vaccine_code") or raw_data.get("code") or "UNKNOWN"),
                vaccine_display=str(raw_data.get("vaccine_display") or raw_data.get("display") or "Vaccine"),
                occurrence_date=raw_data.get("occurrence_date") or raw_data.get("date"),
                primary_source=bool(raw_data.get("primary_source", True)),
                lot_number=raw_data.get("lot_number"),
                created_at=utc_now(),
            )
            domain_buffers["immunizations"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

        elif norm_domain in ["coverages", "insurance"]:
            created_entity = CoverageModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                subscriber_id=raw_data.get("subscriber_id"),
                status=str(raw_data.get("status") or "active"),
                coverage_type=raw_data.get("coverage_type") or raw_data.get("type", "health_insurance"),
                payer_name=str(raw_data.get("payer_name") or raw_data.get("payor_name") or "Insurance Provider"),
                relationship_to_subscriber=raw_data.get("relationship_to_subscriber") or raw_data.get("relationship") or "self",
                period_start=raw_data.get("period_start"),
                period_end=raw_data.get("period_end"),
                created_at=utc_now(),
            )
            coverage_source_map[source_id] = created_entity.id
            if source_id.startswith("Coverage/"):
                coverage_source_map[source_id.replace("Coverage/", "")] = created_entity.id
            domain_buffers["coverages"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

        elif norm_domain in ["claims", "billing"]:
            tot_amt = 0.0
            if raw_data.get("total_amount") is not None:
                try:
                    tot_amt = float(raw_data["total_amount"])
                except Exception:
                    tot_amt = 0.0

            created_entity = ClaimModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                coverage_id=cov_uuid,
                claim_type=str(raw_data.get("claim_type") or raw_data.get("type") or "institutional"),
                use=str(raw_data.get("use") or "claim"),
                status=str(raw_data.get("status") or "active"),
                total_amount=tot_amt,
                currency=str(raw_data.get("currency") or "USD"),
                created_date=raw_data.get("created_date") or raw_data.get("date"),
                created_at=utc_now(),
            )
            domain_buffers["claims"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})
            if not cov_uuid and cov_ref:
                deferred_references.append({"entity": created_entity, "attr": "coverage_id", "source_id": cov_ref, "type": "coverage"})

        elif norm_domain in ["care_plans", "careplans"]:
            created_entity = CarePlanModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                status=str(raw_data.get("status") or "active"),
                intent=str(raw_data.get("intent") or "plan"),
                title=str(raw_data.get("title") or "Care Plan"),
                description=raw_data.get("description"),
                period_start=raw_data.get("period_start"),
                period_end=raw_data.get("period_end"),
                created_at=utc_now(),
            )
            domain_buffers["care_plans"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

        elif norm_domain in ["consents"]:
            created_entity = ConsentModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                status=str(raw_data.get("status") or "active"),
                scope=str(raw_data.get("scope") or "treatment"),
                category=raw_data.get("category"),
                date_time=raw_data.get("date_time") or raw_data.get("date_consented") or raw_data.get("date"),
                created_at=utc_now(),
            )
            domain_buffers["consents"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

        elif norm_domain in ["service_requests", "orders"]:
            created_entity = ServiceRequestModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                status=str(raw_data.get("status") or "active"),
                intent=str(raw_data.get("intent") or "order"),
                code=str(raw_data.get("code") or "UNKNOWN"),
                display=str(raw_data.get("display") or "Service Request"),
                authored_on=raw_data.get("authored_on") or raw_data.get("date"),
                created_at=utc_now(),
            )
            service_request_source_map[source_id] = created_entity.id
            if source_id.startswith("ServiceRequest/"):
                service_request_source_map[source_id.replace("ServiceRequest/", "")] = created_entity.id
            domain_buffers["service_requests"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["diagnostic_reports"]:
            created_entity = DiagnosticReportModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                service_request_id=srv_req_uuid,
                status=str(raw_data.get("status") or "final"),
                category=str(raw_data.get("category") or "LAB"),
                code=str(raw_data.get("code") or "UNKNOWN"),
                display=str(raw_data.get("display") or "Diagnostic Report"),
                effective_date=raw_data.get("effective_date") or raw_data.get("date"),
                conclusion=raw_data.get("conclusion"),
                created_at=utc_now(),
            )
            domain_buffers["diagnostic_reports"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})
            if not srv_req_uuid and srv_req_ref:
                deferred_references.append({"entity": created_entity, "attr": "service_request_id", "source_id": srv_req_ref, "type": "service_request"})

        elif norm_domain in ["imaging_studies", "imaging"]:
            num_series = 1
            if raw_data.get("number_of_series") is not None:
                try:
                    num_series = int(raw_data["number_of_series"])
                except Exception:
                    num_series = 1

            num_instances = 1
            if raw_data.get("number_of_instances") is not None:
                try:
                    num_instances = int(raw_data["number_of_instances"])
                except Exception:
                    num_instances = 1

            created_entity = ImagingStudyModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                modality=str(raw_data.get("modality") or "CT"),
                description=raw_data.get("description"),
                started_date=raw_data.get("started_date") or raw_data.get("started_at") or raw_data.get("date"),
                number_of_series=num_series,
                number_of_instances=num_instances,
                created_at=utc_now(),
            )
            domain_buffers["imaging_studies"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["documents", "clinical_notes", "notes"]:
            created_entity = DocumentReferenceModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                source_id=source_id,
                patient_id=patient_uuid,
                encounter_id=enc_uuid,
                status=str(raw_data.get("status") or "current"),
                doc_type=str(raw_data.get("doc_type") or raw_data.get("type") or raw_rec.metadata.get("record_type") or "clinical_note"),
                category=raw_data.get("category"),
                date=raw_data.get("date") or raw_rec.metadata.get("record_date"),
                description=raw_data.get("description"),
                content_text=str(raw_data.get("content_text") or raw_rec.raw_document or ""),
                created_at=utc_now(),
            )
            domain_buffers["document_references"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})
            if not enc_uuid and enc_ref:
                deferred_references.append({"entity": created_entity, "attr": "encounter_id", "source_id": enc_ref, "type": "encounter"})

        elif norm_domain in ["provenances", "provenance"]:
            prov_source_id = str(
                raw_data.get("provenance_id")
                or raw_data.get("id")
                or raw_rec.source_record_id
                or generate_uuid()
            )
            rec_at = utc_now()
            raw_rec_at = raw_data.get("recorded_at") or raw_data.get("date")
            if raw_rec_at:
                try:
                    parsed_dt = datetime.fromisoformat(str(raw_rec_at).replace("Z", "+00:00"))
                    rec_at = parsed_dt if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    rec_at = utc_now()

            target_type = str(raw_data.get("target_resource_type") or "Patient")
            target_id = str(raw_data.get("target_resource_id") or raw_data.get("patient_id") or source_id)
            if target_type.lower() == "patient" and patient_uuid:
                target_id = patient_uuid

            created_entity = ProvenanceModel(
                id=generate_uuid(),
                job_id=job_id,
                source_system=source_system,
                patient_id=patient_uuid,
                target_resource_type=target_type,
                target_resource_id=target_id,
                recorded_at=rec_at,
                activity=str(raw_data.get("activity") or "record-generation"),
                agent_name=raw_data.get("agent_name") or raw_data.get("agent_id") or raw_data.get("agent") or "SYSTEM",
                agent_role=raw_data.get("agent_role") or "author",
                metadata_json={
                    "source_provenance_id": prov_source_id,
                    "patient_id": raw_data.get("patient_id") or patient_ref,
                    "signature_status": raw_data.get("signature_status"),
                },
                created_at=utc_now(),
            )
            domain_buffers["provenances"].append(created_entity)
            if not patient_uuid and patient_ref:
                deferred_references.append({"entity": created_entity, "attr": "patient_id", "source_id": patient_ref, "type": "patient"})

    async def _flush_domain_buffers(self, domain_buffers: Dict[str, List[Any]], threshold: int = 100) -> None:
        """Flush in-memory entity buffers to database in strict dependency order."""
        if threshold > 0:
            if not any(len(items) >= threshold for items in domain_buffers.values()):
                return

        flush_order = [
            "organizations",
            "practitioners",
            "coverages",
            "encounters",
            "service_requests",
            "medication_requests",
            "conditions",
            "observations",
            "medication_administrations",
            "procedures",
            "allergies",
            "immunizations",
            "claims",
            "care_plans",
            "consents",
            "diagnostic_reports",
            "imaging_studies",
            "document_references",
            "provenances",
            "clinical_records",
            "audit_logs",
        ]

        for domain in flush_order:
            items = domain_buffers.get(domain)
            if not items:
                continue

            if domain == "organizations":
                await self.domain_repo.bulk_create_organizations(items)
            elif domain == "practitioners":
                await self.domain_repo.bulk_create_practitioners(items)
            elif domain == "encounters":
                await self.domain_repo.bulk_create_encounters(items)
            elif domain == "conditions":
                await self.domain_repo.bulk_create_conditions(items)
            elif domain == "observations":
                await self.domain_repo.bulk_create_observations(items)
            elif domain == "medication_requests":
                await self.domain_repo.bulk_create_medication_requests(items)
            elif domain == "medication_administrations":
                await self.domain_repo.bulk_create_medication_administrations(items)
            elif domain == "procedures":
                await self.domain_repo.bulk_create_procedures(items)
            elif domain == "allergies":
                await self.domain_repo.bulk_create_allergies(items)
            elif domain == "immunizations":
                await self.domain_repo.bulk_create_immunizations(items)
            elif domain == "coverages":
                await self.domain_repo.bulk_create_coverages(items)
            elif domain == "claims":
                await self.domain_repo.bulk_create_claims(items)
            elif domain == "care_plans":
                await self.domain_repo.bulk_create_care_plans(items)
            elif domain == "consents":
                await self.domain_repo.bulk_create_consents(items)
            elif domain == "service_requests":
                await self.domain_repo.bulk_create_service_requests(items)
            elif domain == "diagnostic_reports":
                await self.domain_repo.bulk_create_diagnostic_reports(items)
            elif domain == "imaging_studies":
                await self.domain_repo.bulk_create_imaging_studies(items)
            elif domain == "document_references":
                await self.domain_repo.bulk_create_document_references(items)
            elif domain == "provenances":
                await self.domain_repo.bulk_create_provenances(items)
            elif domain == "clinical_records":
                await self.record_repo.bulk_create_records(items)
            elif domain == "audit_logs":
                await self.audit_repo.bulk_append_audit_logs(items)

            items.clear()
        await self.session.commit()

    async def _resolve_deferred_references(
        self,
        deferred_references: List[Dict[str, Any]],
        patient_source_map: Dict[str, str],
        encounter_source_map: Dict[str, str],
        coverage_source_map: Dict[str, str],
        practitioner_source_map: Dict[str, str],
        organization_source_map: Dict[str, str],
        medication_request_source_map: Dict[str, str],
        service_request_source_map: Dict[str, str],
    ) -> None:
        """Second-pass resolution of foreign keys that were out-of-order during initial file ingestion."""
        for item in deferred_references:
            entity = item["entity"]
            attr = item["attr"]
            src_id = item["source_id"]
            ref_type = item["type"]

            resolved_val: Optional[str] = None
            if ref_type == "patient":
                resolved_val = patient_source_map.get(src_id)
            elif ref_type == "encounter":
                resolved_val = encounter_source_map.get(src_id)
            elif ref_type == "coverage":
                resolved_val = coverage_source_map.get(src_id)
            elif ref_type == "practitioner":
                resolved_val = practitioner_source_map.get(src_id)
            elif ref_type == "organization":
                resolved_val = organization_source_map.get(src_id)
            elif ref_type == "medication_request":
                resolved_val = medication_request_source_map.get(src_id)
            elif ref_type == "service_request":
                resolved_val = service_request_source_map.get(src_id)

            if resolved_val:
                setattr(entity, attr, resolved_val)

        await self.session.commit()

    # =========================================================================
    # Patient Demographic Normalization & Identity Reconciliation
    # =========================================================================

    async def _process_single_record(
        self,
        job_id: str,
        raw_rec: RawRecord,
        source_system: str,
        mapping: MappingProfile,
        patient_cache: Optional[Dict[Tuple[str, str], PatientModel]] = None,
        fingerprint_cache: Optional[Dict[str, ClinicalRecordModel]] = None,
    ) -> Tuple[Optional[ClinicalRecordModel], List[AuditLogModel], bool, bool, bool, bool, bool]:
        """Process a single raw record: validate, normalize, reconcile identity, deduplicate, and audit."""
        audit_records: List[AuditRecord] = []
        is_success = False
        is_rejected = False
        is_dup = False
        is_warn = False
        is_conflict = False

        record_id = generate_uuid()
        raw_patient = raw_rec.raw_patient or {}
        raw_doc = raw_rec.raw_document

        candidate_patient, demo_audits, validation_issues = DemographicNormalizer.normalize_patient(
            raw_data=raw_patient,
            source_system=source_system,
            job_id=job_id,
            mapping=mapping,
        )
        audit_records.extend(demo_audits)

        patient_db_id: Optional[str] = None
        decision: Optional[ReconciliationDecision] = None
        patient_ref: Optional[str] = None

        if not candidate_patient:
            patient_ref = self.extract_patient_reference(raw_patient, raw_rec)
            if patient_ref:
                cache_key = (source_system.lower(), patient_ref)
                existing_p = None
                if patient_cache is not None and cache_key in patient_cache:
                    existing_p = patient_cache[cache_key]
                else:
                    existing_p = await self.patient_repo.find_patient_by_identifier(
                        patient_ref, source_system=source_system
                    )

                if existing_p:
                    patient_db_id = existing_p.id
                    if patient_cache is not None:
                        patient_cache[cache_key] = existing_p
                    audit_records.append(
                        AuditRecord(
                            audit_id=generate_uuid(),
                            job_id=job_id,
                            record_id=record_id,
                            field_name="patient_id",
                            original_value=patient_ref,
                            normalized_value=patient_db_id,
                            transformation_applied="PATIENT_AUTO_LINKED",
                            reason=f"Automatically linked to existing patient record via identifier '{patient_ref}'",
                            processing_component="IngestionOrchestrator",
                            outcome=AuditOutcome.SUCCESS,
                        )
                    )
                else:
                    placeholder_patient = PatientModel(
                        id=generate_uuid(),
                        source_system=source_system,
                        source_patient_id=patient_ref,
                        mrn=patient_ref,
                        first_name="UNRESOLVED",
                        last_name="PATIENT",
                        reconciliation_status=ReconciliationStatus.MANUAL_REVIEW_REQUIRED.value,
                        confidence_score=0.0,
                    )
                    ident = PatientIdentifierModel(
                        id=generate_uuid(),
                        patient_id=placeholder_patient.id,
                        identifier_type="MRN",
                        value=patient_ref,
                        issuing_authority=source_system,
                    )
                    await self.patient_repo.create_patient(placeholder_patient, [ident])
                    patient_db_id = placeholder_patient.id
                    if patient_cache is not None:
                        patient_cache[cache_key] = placeholder_patient
                    audit_records.append(
                        AuditRecord(
                            audit_id=generate_uuid(),
                            job_id=job_id,
                            record_id=record_id,
                            field_name="patient_id",
                            original_value=patient_ref,
                            normalized_value=patient_db_id,
                            transformation_applied="PLACEHOLDER_PATIENT_CREATED",
                            reason=f"Created placeholder patient for identifier '{patient_ref}' awaiting demographic record",
                            processing_component="IngestionOrchestrator",
                            outcome=AuditOutcome.SUCCESS,
                        )
                    )
            else:
                is_rejected = True
                rec_model = ClinicalRecordModel(
                    id=record_id,
                    job_id=job_id,
                    patient_id=None,
                    record_type=raw_rec.metadata.get("record_type", "clinical_record"),
                    status=RecordStatus.REJECTED.value,
                    fingerprint="REJECTED_" + generate_uuid(),
                    source_record_id=raw_rec.source_record_id,
                    cleaned_text=None,
                    original_content=str(raw_doc) if raw_doc else None,
                    parsed_payload=raw_patient,
                    metadata_json=raw_rec.metadata,
                    validation_errors=validation_issues,
                )
                audit_records.append(
                    AuditRecord(
                        audit_id=generate_uuid(),
                        job_id=job_id,
                        record_id=record_id,
                        field_name="patient",
                        original_value=None,
                        normalized_value=None,
                        transformation_applied="RECORD_VALIDATION_REJECTED",
                        reason="Mandatory demographic identifiers (MRN or patient ID) missing",
                        processing_component="DemographicNormalizer",
                        outcome=AuditOutcome.FAILURE,
                    )
                )
                audit_models = [self._to_audit_model(a, job_id, record_id) for a in audit_records]
                return rec_model, audit_models, False, True, False, False, False
        else:
            cache_key = (source_system.lower(), candidate_patient.mrn)
            if patient_cache is not None and cache_key in patient_cache:
                existing_by_mrn = [patient_cache[cache_key]]
                existing_by_demo = []
            else:
                existing_by_mrn = await self.patient_repo.find_by_scoped_mrn(
                    source_system=source_system, mrn=candidate_patient.mrn
                )
                existing_by_demo = await self.patient_repo.find_by_demographics(
                    last_name=candidate_patient.last_name,
                    first_name=candidate_patient.first_name,
                    date_of_birth=candidate_patient.date_of_birth,
                )

            decision = PatientIdentityReconciler.reconcile(
                candidate=candidate_patient,
                existing_patients_by_mrn=existing_by_mrn,
                existing_patients_by_demographics=existing_by_demo,
                job_id=job_id,
            )
            audit_records.extend(decision.audit_events)

            if decision.status == ReconciliationStatus.MATCHED:
                patient_db_id = decision.matched_patient.id  # type: ignore
                if decision.matched_patient:
                    if decision.matched_patient.first_name == "UNRESOLVED":
                        decision.matched_patient.first_name = candidate_patient.first_name
                        decision.matched_patient.middle_name = candidate_patient.middle_name
                        decision.matched_patient.last_name = candidate_patient.last_name
                        decision.matched_patient.date_of_birth = candidate_patient.date_of_birth
                        decision.matched_patient.administrative_gender = candidate_patient.administrative_gender
                        decision.matched_patient.contact_info = candidate_patient.contact_info
                        decision.matched_patient.reconciliation_status = ReconciliationStatus.MATCHED.value
                        decision.matched_patient.confidence_score = 1.0
                    if patient_cache is not None:
                        patient_cache[cache_key] = decision.matched_patient
            elif decision.status == ReconciliationStatus.NEW_PATIENT:
                new_p = PatientModel(
                    id=candidate_patient.id,
                    source_system=candidate_patient.source_system,
                    source_patient_id=candidate_patient.source_patient_id,
                    mrn=candidate_patient.mrn,
                    original_mrn=candidate_patient.original_mrn,
                    first_name=candidate_patient.first_name,
                    middle_name=candidate_patient.middle_name,
                    last_name=candidate_patient.last_name,
                    date_of_birth=candidate_patient.date_of_birth,
                    original_date_of_birth=candidate_patient.original_date_of_birth,
                    administrative_gender=candidate_patient.administrative_gender,
                    original_gender=candidate_patient.original_gender,
                    contact_info=candidate_patient.contact_info,
                    reconciliation_status=decision.status.value,
                    confidence_score=decision.confidence_score,
                )
                ident = PatientIdentifierModel(
                    id=generate_uuid(),
                    patient_id=new_p.id,
                    identifier_type="MRN",
                    value=candidate_patient.mrn,
                    issuing_authority=source_system,
                )
                await self.patient_repo.create_patient(new_p, [ident])
                patient_db_id = new_p.id
                if patient_cache is not None:
                    patient_cache[cache_key] = new_p
            elif decision.status == ReconciliationStatus.IDENTITY_CONFLICT:
                is_conflict = True
                validation_issues.append({"field": "identity", "error": decision.conflict_details})
                patient_db_id = None
            elif decision.status in [ReconciliationStatus.POSSIBLE_DUPLICATE, ReconciliationStatus.MANUAL_REVIEW_REQUIRED]:
                is_warn = True
                new_p = PatientModel(
                    id=candidate_patient.id,
                    source_system=candidate_patient.source_system,
                    source_patient_id=candidate_patient.source_patient_id,
                    mrn=candidate_patient.mrn,
                    original_mrn=candidate_patient.original_mrn,
                    first_name=candidate_patient.first_name,
                    middle_name=candidate_patient.middle_name,
                    last_name=candidate_patient.last_name,
                    date_of_birth=candidate_patient.date_of_birth,
                    original_date_of_birth=candidate_patient.original_date_of_birth,
                    administrative_gender=candidate_patient.administrative_gender,
                    original_gender=candidate_patient.original_gender,
                    contact_info=candidate_patient.contact_info,
                    reconciliation_status=decision.status.value,
                    confidence_score=decision.confidence_score,
                )
                ident = PatientIdentifierModel(
                    id=generate_uuid(),
                    patient_id=new_p.id,
                    identifier_type="MRN",
                    value=candidate_patient.mrn,
                    issuing_authority=source_system,
                )
                await self.patient_repo.create_patient(new_p, [ident])
                patient_db_id = new_p.id
                if patient_cache is not None:
                    patient_cache[cache_key] = new_p

        raw_text_content = ""
        structured_payload: Optional[Dict[str, Any]] = None
        if isinstance(raw_doc, str):
            raw_text_content = raw_doc
        elif isinstance(raw_doc, dict):
            structured_payload = raw_doc
            raw_text_content = (
                raw_doc.get("clinical_note")
                or raw_doc.get("text")
                or raw_doc.get("report")
                or raw_doc.get("notes")
                or ""
            )

        cleaned_text, clean_txs = ClinicalTextCleaner.clean(raw_text_content)
        for tx in clean_txs:
            audit_records.append(
                AuditRecord(
                    audit_id=generate_uuid(),
                    job_id=job_id,
                    record_id=record_id,
                    field_name="clinical_text",
                    original_value="[RAW_TEXT]",
                    normalized_value="[CLEANED_TEXT]",
                    transformation_applied=tx,
                    reason="Conservative clinical text normalization applied",
                    processing_component="ClinicalTextCleaner",
                    outcome=AuditOutcome.SUCCESS,
                )
            )

        raw_rec_date = raw_rec.metadata.get("record_date")
        norm_rec_date = None
        if raw_rec_date:
            date_res = DateNormalizer.normalize_timestamp(raw_rec_date, format_hint=mapping.date_format_hint)
            if date_res.is_valid:
                norm_rec_date = date_res.normalized_value
            elif date_res.is_ambiguous:
                is_warn = True
                validation_issues.append({"field": "record_date", "error": date_res.error_message})

        content_hash = RecordFingerprinter.compute_content_hash(
            content=cleaned_text, payload=structured_payload
        )
        rec_type = raw_rec.metadata.get("record_type", "clinical_record")
        patient_mrn_for_fingerprint = candidate_patient.mrn if candidate_patient else (patient_ref or "UNKNOWN")
        fingerprint = RecordFingerprinter.generate_fingerprint(
            source_system=source_system,
            patient_mrn=patient_mrn_for_fingerprint,
            record_type=rec_type,
            record_date=norm_rec_date,
            content_hash=content_hash,
            source_record_id=raw_rec.source_record_id,
        )

        existing_record = None
        if fingerprint_cache is not None and fingerprint in fingerprint_cache:
            existing_record = fingerprint_cache[fingerprint]
        else:
            existing_record = await self.record_repo.find_by_fingerprint(fingerprint)
            if existing_record and fingerprint_cache is not None:
                fingerprint_cache[fingerprint] = existing_record

        rec_status = RecordStatus.NORMALIZED.value

        if existing_record:
            is_dup = True
            rec_status = RecordStatus.DUPLICATE.value
            audit_records.append(
                AuditRecord(
                    audit_id=generate_uuid(),
                    job_id=job_id,
                    record_id=record_id,
                    field_name="fingerprint",
                    original_value=fingerprint,
                    normalized_value=existing_record.id,
                    transformation_applied="EXACT_DUPLICATE_DETECTED",
                    reason="Exact duplicate record detected matching existing record fingerprint",
                    processing_component="RecordFingerprinter",
                    outcome=AuditOutcome.WARNING,
                )
            )
        elif decision and decision.status == ReconciliationStatus.IDENTITY_CONFLICT:
            rec_status = RecordStatus.MANUAL_REVIEW_REQUIRED.value
        elif decision and decision.status in [ReconciliationStatus.POSSIBLE_DUPLICATE, ReconciliationStatus.MANUAL_REVIEW_REQUIRED]:
            rec_status = RecordStatus.MANUAL_REVIEW_REQUIRED.value
        elif validation_issues and candidate_patient:
            rec_status = RecordStatus.MANUAL_REVIEW_REQUIRED.value
            is_warn = True
        else:
            is_success = True

        rec_model = ClinicalRecordModel(
            id=record_id,
            job_id=job_id,
            patient_id=patient_db_id,
            record_type=rec_type,
            status=rec_status,
            fingerprint=fingerprint,
            source_record_id=raw_rec.source_record_id,
            record_date=norm_rec_date,
            original_record_date=raw_rec_date,
            cleaned_text=cleaned_text if cleaned_text else None,
            original_content=str(raw_doc) if raw_doc else None,
            parsed_payload=structured_payload or raw_patient,
            metadata_json=raw_rec.metadata,
            validation_errors=validation_issues if validation_issues else None,
        )

        if fingerprint_cache is not None and rec_status != RecordStatus.DUPLICATE.value:
            fingerprint_cache[fingerprint] = rec_model

        audit_models = [self._to_audit_model(a, job_id, record_id) for a in audit_records]
        return rec_model, audit_models, is_success, is_rejected, is_dup, is_warn, is_conflict

    @staticmethod
    def _to_audit_model(record: AuditRecord, job_id: str, record_id: str) -> AuditLogModel:
        """Convert Pydantic AuditRecord to SQLAlchemy AuditLogModel."""
        return AuditLogModel(
            id=record.audit_id,
            job_id=job_id,
            record_id=record.record_id or record_id,
            field_name=record.field_name,
            original_value=str(record.original_value) if record.original_value is not None else None,
            normalized_value=str(record.normalized_value) if record.normalized_value is not None else None,
            transformation_applied=record.transformation_applied,
            reason=record.reason,
            component=record.processing_component,
            outcome=record.outcome.value if hasattr(record.outcome, "value") else str(record.outcome),
            timestamp=record.timestamp,
        )

    # =========================================================================
    # Reporting & Metrics
    # =========================================================================

    async def generate_report(self, job_id: str) -> IngestionReportResponse:
        """Generate comprehensive post-ingestion report with counts, reconciliation stats, domains, and audits."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise AppException(f"Ingestion job '{job_id}' not found", status_code=404)

        duration: Optional[float] = None
        if job.started_at and job.completed_at:
            s = job.started_at if job.started_at.tzinfo else job.started_at.replace(tzinfo=timezone.utc)
            c = job.completed_at if job.completed_at.tzinfo else job.completed_at.replace(tzinfo=timezone.utc)
            duration = (c - s).total_seconds()

        job_resp = IngestionJobResponse(
            job_id=job.id,
            status=JobStatus(job.status),
            source_format=job.source_format,
            source_system=job.source_system,
            total_records=job.total_records,
            successful_records=job.successful_records,
            rejected_records=job.rejected_records,
            duplicate_records=job.duplicate_records,
            warning_records=job.warning_records,
            conflict_records=job.conflict_records,
            error_message=job.error_message,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            duration_seconds=duration,
        )

        audit_logs = await self.audit_repo.get_audit_logs_for_job(job_id, limit=50)
        recent_audits = [
            AuditRecord(
                audit_id=log.id,
                job_id=log.job_id,
                record_id=log.record_id,
                field_name=log.field_name,
                original_value=log.original_value,
                normalized_value=log.normalized_value,
                transformation_applied=log.transformation_applied,
                reason=log.reason,
                timestamp=log.timestamp,
                processing_component=log.component,
                outcome=AuditOutcome(log.outcome),
            )
            for log in audit_logs
        ]

        warnings: List[str] = []
        if job.conflict_records > 0:
            warnings.append(f"{job.conflict_records} identity conflict(s) detected and escalated for manual review.")
        if job.warning_records > 0:
            warnings.append(f"{job.warning_records} record(s) flagged with validation warnings.")
        if job.duplicate_records > 0:
            warnings.append(f"{job.duplicate_records} duplicate record(s) detected.")
        if job.rejected_records > 0:
            warnings.append(f"{job.rejected_records} invalid record(s) rejected due to missing mandatory identifiers.")

        domain_counts = await self.domain_repo.get_domain_counts_for_job(job_id)
        integrity_report = await self.domain_repo.get_referential_integrity_report(job_id)

        package_file_models = await self.domain_repo.get_package_files_for_job(job_id)
        package_file_resps = [
            PackageFileResponse(
                id=pf.id,
                job_id=pf.job_id,
                file_path=pf.file_path,
                domain=pf.domain,
                format=pf.format,
                status=pf.status,
                total_records=pf.total_records,
                successful_records=pf.successful_records,
                rejected_records=pf.rejected_records,
                error_message=pf.error_message,
                created_at=pf.created_at,
                completed_at=pf.completed_at,
            )
            for pf in package_file_models
        ]

        return IngestionReportResponse(
            job=job_resp,
            reconciliation_summary={
                "successful": job.successful_records,
                "conflicts": job.conflict_records,
                "duplicates": job.duplicate_records,
                "warnings": job.warning_records,
                "rejected": job.rejected_records,
            },
            duplicate_summary={
                "total_duplicates_detected": job.duplicate_records,
                "exact_duplicates_skipped": job.duplicate_records,
            },
            warnings=warnings,
            recent_audit_events=recent_audits,
            domain_summary=domain_counts,
            referential_integrity=integrity_report,
            package_files=package_file_resps,
        )
