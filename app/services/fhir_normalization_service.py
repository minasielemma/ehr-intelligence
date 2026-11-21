"""Service orchestrating HL7 FHIR R4 Normalization, Validation, and Dual-Layer Storage.

Implements per-patient processing isolation, referential graph assembly,
strict gatekeeper validation, and atomic persistence.
"""

from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ValidationException
from app.core.logging import get_logger
from app.fhir.bundler import FHIRBundleBuilder
from app.fhir.mapper import FHIRMapper
from app.fhir.storage import FHIRBundleFileStorage
from app.fhir.validator import FHIRValidator
from app.models.ingestion import (
    ClinicalRecordModel,
    DiagnosticReportModel,
    EncounterModel,
    ObservationModel,
    PatientModel,
)
from app.repositories.domain_repository import DomainRepository
from app.repositories.fhir_bundle_repository import FHIRBundleRepository, compute_bundle_hash
from app.repositories.patient_repository import PatientRepository
from app.schemas.canonical import CanonicalClinicalRecord, CanonicalPatient
from app.schemas.fhir import (
    FHIRNormalizationResponse,
    FHIRValidationReport,
    ValidationStatus,
)

logger = get_logger(__name__)


class FHIRNormalizationService:
    """Orchestrates transformation of cleaned EHR intermediate representations into validated FHIR Bundles."""

    def __init__(
        self,
        session: AsyncSession,
        file_storage: Optional[FHIRBundleFileStorage] = None,
    ) -> None:
        self.session = session
        self.patient_repo = PatientRepository(session)
        self.domain_repo = DomainRepository(session)
        self.bundle_repo = FHIRBundleRepository(session)
        self.file_storage = file_storage or FHIRBundleFileStorage()

    async def normalize_patient_bundle(
        self,
        patient: Union[CanonicalPatient, PatientModel, Dict[str, Any]],
        records: Optional[List[Union[CanonicalClinicalRecord, ClinicalRecordModel, Dict[str, Any]]]] = None,
        encounters: Optional[List[Union[EncounterModel, Dict[str, Any]]]] = None,
        diagnostic_reports: Optional[List[Union[DiagnosticReportModel, Dict[str, Any]]]] = None,
        observations: Optional[List[Union[ObservationModel, Dict[str, Any]]]] = None,
        bundle_type: str = "collection",
        bundle_id: Optional[str] = None,
        save_to_store: bool = True,
    ) -> FHIRNormalizationResponse:
        """Map cleaned patient data and associated records into a validated FHIR R4 Bundle.

        Enforces gatekeeper validation: invalid bundles are NEVER persisted to the validated output store.
        """
        fhir_patient = FHIRMapper.to_fhir_patient(patient)
        patient_id = fhir_patient["id"]
        patient_mrn = fhir_patient.get("identifier", [{}])[0].get("value", "UNKNOWN")

        builder = FHIRBundleBuilder(
            patient_id=patient_id,
            bundle_id=bundle_id,
            bundle_type=bundle_type,
        )
        builder.add_resource(fhir_patient)

        if encounters:
            for enc in encounters:
                fhir_enc = FHIRMapper.to_fhir_encounter(enc, patient_id=patient_id)
                builder.add_resource(fhir_enc)

        obs_map: Dict[str, Dict[str, Any]] = {}
        obs_by_enc: Dict[str, List[str]] = {}
        if observations:
            for obs in observations:
                fhir_obs = FHIRMapper.to_fhir_observation(obs, patient_id=patient_id)
                builder.add_resource(fhir_obs)
                obs_map[fhir_obs["id"]] = fhir_obs
                enc_id = getattr(obs, "encounter_id", None) if hasattr(obs, "encounter_id") else obs.get("encounter_id")
                if enc_id:
                    obs_by_enc.setdefault(str(enc_id), []).append(fhir_obs["id"])

        if diagnostic_reports:
            for dr in diagnostic_reports:
                dr_enc = getattr(dr, "encounter_id", None) if hasattr(dr, "encounter_id") else dr.get("encounter_id")
                linked_obs_ids = None
                if dr_enc and str(dr_enc) in obs_by_enc:
                    linked_obs_ids = obs_by_enc[str(dr_enc)]
                elif not encounters and obs_map and len(diagnostic_reports) == 1:
                    linked_obs_ids = list(obs_map.keys())

                fhir_dr = FHIRMapper.to_fhir_diagnostic_report(
                    dr,
                    patient_id=patient_id,
                    observation_ids=linked_obs_ids,
                )
                builder.add_resource(fhir_dr)

        if records:
            for rec in records:
                fhir_doc = FHIRMapper.to_fhir_document_reference(rec, patient_id=patient_id)
                builder.add_resource(fhir_doc)

        try:
            bundle_dict = builder.build()
        except Exception as exc:
            logger.error("Failed to assemble bundle for patient [%s]: %s", patient_id, exc)
            report = FHIRValidationReport(
                patient_identifier=patient_mrn,
                bundle_id=bundle_id,
                status=ValidationStatus.INVALID,
                total_resources=len(builder.resources),
                valid_resources=0,
                invalid_resources=len(builder.resources),
                error_count=1,
                warning_count=0,
                info_count=0,
            )
            return FHIRNormalizationResponse(
                success=False,
                bundle_id=bundle_id,
                patient_id=patient_id,
                patient_mrn=patient_mrn,
                bundle=None,
                validation_report=report,
                persisted=False,
            )

        validation_report = FHIRValidator.validate_bundle_detailed(
            bundle_data=bundle_dict,
            expected_patient_id=patient_id,
        )

        is_valid = validation_report.status in [ValidationStatus.VALID, ValidationStatus.WARNING]

        saved_file_path: Optional[str] = None
        bundle_model = None
        version = 1

        if is_valid and save_to_store:
            c_hash = compute_bundle_hash(bundle_dict)
            existing_dup = await self.bundle_repo.get_by_patient_hash(patient_id, c_hash)
            if existing_dup:
                logger.info("Found existing identical FHIR Bundle [%s] (v%d) for patient [%s]", existing_dup.bundle_id, existing_dup.version, patient_id)
                return FHIRNormalizationResponse(
                    success=True,
                    bundle_id=existing_dup.bundle_id,
                    patient_id=patient_id,
                    patient_mrn=patient_mrn,
                    version=existing_dup.version,
                    bundle=existing_dup.bundle_json,
                    validation_report=validation_report,
                    storage_path=existing_dup.file_path,
                    persisted=True,
                )

            existing_p = await self.patient_repo.get_by_id(patient_id)
            if not existing_p:
                src_sys = getattr(patient, "source_system", None) if hasattr(patient, "source_system") else patient.get("source_system")
                p_names = fhir_patient.get("name", [{}])[0]
                givens = p_names.get("given", ["UNKNOWN"])
                new_pat = PatientModel(
                    id=patient_id,
                    source_system=src_sys or "direct_fhir",
                    mrn=patient_mrn,
                    first_name=givens[0] if givens else "UNKNOWN",
                    middle_name=givens[1] if len(givens) > 1 else None,
                    last_name=p_names.get("family", "UNKNOWN"),
                    date_of_birth=fhir_patient.get("birthDate"),
                    administrative_gender=fhir_patient.get("gender", "unknown"),
                    confidence_score=1.0,
                )
                self.session.add(new_pat)
                await self.session.flush()

            target_version = await self.bundle_repo.get_next_version(patient_id)

            try:
                saved_file_path = self.file_storage.save_bundle(
                    patient_id=patient_id,
                    bundle_id=bundle_dict["id"],
                    bundle_data=bundle_dict,
                    version=target_version,
                )
            except Exception as exc:
                logger.warning("Filesystem persistence warning for bundle [%s]: %s", bundle_dict["id"], exc)

            bundle_model, is_new = await self.bundle_repo.save_bundle(
                bundle_id=bundle_dict["id"],
                patient_id=patient_id,
                patient_mrn=patient_mrn,
                bundle_type=bundle_type,
                bundle_json=bundle_dict,
                status=validation_report.status.value,
                resource_count=len(bundle_dict.get("entry", [])),
                validation_report_json=validation_report.model_dump(mode="json"),
                file_path=saved_file_path,
                metadata_json={"source": "FHIRNormalizationService"},
                content_hash=c_hash,
                version=target_version,
            )
            version = bundle_model.version
            await self.session.commit()
            logger.info("Successfully validated and persisted FHIR Bundle [%s] (v%d) for patient [%s]", bundle_dict["id"], version, patient_id)
        elif not is_valid:
            logger.warning(
                "Gatekeeper rejected invalid FHIR Bundle [%s] for patient [%s]. Errors: %d. Bundle NOT persisted.",
                bundle_dict["id"],
                patient_id,
                validation_report.error_count,
            )

        return FHIRNormalizationResponse(
            success=is_valid,
            bundle_id=bundle_dict["id"],
            patient_id=patient_id,
            patient_mrn=patient_mrn,
            version=version,
            bundle=bundle_dict,
            validation_report=validation_report,
            storage_path=saved_file_path,
            persisted=is_valid and save_to_store,
        )

    async def normalize_db_patient(
        self,
        patient_id: str,
        bundle_type: str = "collection",
        save_to_store: bool = True,
    ) -> FHIRNormalizationResponse:
        """Fetch a reconciled patient and all longitudinal records from the database and normalize to FHIR."""
        patient = await self.patient_repo.get_by_id(patient_id)
        if not patient:
            raise AppException(f"Patient with ID '{patient_id}' not found", status_code=404)

        cr_stmt = select(ClinicalRecordModel).where(ClinicalRecordModel.patient_id == patient_id)
        records = list((await self.session.execute(cr_stmt)).scalars().all())

        enc_stmt = select(EncounterModel).where(EncounterModel.patient_id == patient_id)
        encounters = list((await self.session.execute(enc_stmt)).scalars().all())

        dr_stmt = select(DiagnosticReportModel).where(DiagnosticReportModel.patient_id == patient_id)
        diag_reports = list((await self.session.execute(dr_stmt)).scalars().all())

        obs_stmt = select(ObservationModel).where(ObservationModel.patient_id == patient_id)
        observations = list((await self.session.execute(obs_stmt)).scalars().all())

        return await self.normalize_patient_bundle(
            patient=patient,
            records=records,
            encounters=encounters,
            diagnostic_reports=diag_reports,
            observations=observations,
            bundle_type=bundle_type,
            save_to_store=save_to_store,
        )

    async def normalize_job(
        self,
        job_id: str,
        bundle_type: str = "collection",
        save_to_store: bool = True,
    ) -> List[FHIRNormalizationResponse]:
        """Normalize all reconciled patients and associated records from an Ingestion Job.

        Enforces per-patient processing isolation so a defect in one patient never corrupts or halts others.
        """
        patient_ids: List[str] = []

        cr_pat_stmt = (
            select(ClinicalRecordModel.patient_id)
            .where(ClinicalRecordModel.job_id == job_id, ClinicalRecordModel.patient_id.isnot(None))
            .distinct()
        )
        cr_pat_results = (await self.session.execute(cr_pat_stmt)).scalars().all()
        for pid in cr_pat_results:
            if pid and pid not in patient_ids:
                patient_ids.append(pid)

        enc_pat_stmt = (
            select(EncounterModel.patient_id)
            .where(EncounterModel.job_id == job_id)
            .distinct()
        )
        enc_pat_results = (await self.session.execute(enc_pat_stmt)).scalars().all()
        for pid in enc_pat_results:
            if pid and pid not in patient_ids:
                patient_ids.append(pid)

        logger.info("Found %d distinct reconciled patients to normalize for job [%s]", len(patient_ids), job_id)

        responses: List[FHIRNormalizationResponse] = []
        for pid in patient_ids:
            try:
                res = await self.normalize_db_patient(
                    patient_id=pid,
                    bundle_type=bundle_type,
                    save_to_store=save_to_store,
                )
                responses.append(res)
            except Exception as exc:
                try:
                    await self.session.rollback()
                except Exception:
                    pass
                logger.error("Isolated normalization failure for patient [%s] in job [%s]: %s", pid, job_id, exc)
                fail_report = FHIRValidationReport(
                    patient_identifier=pid,
                    status=ValidationStatus.INVALID,
                    error_count=1,
                    issues=[],
                )
                responses.append(
                    FHIRNormalizationResponse(
                        success=False,
                        patient_id=pid,
                        validation_report=fail_report,
                        persisted=False,
                    )
                )

        return responses
