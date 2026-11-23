"""FastAPI router for clinical patient management, longitudinal records, and FHIR resource inspection."""

import math
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.models.database import get_db_session
from app.models.ingestion import (
    ClinicalRecordModel,
    ConditionModel,
    DiagnosticReportModel,
    DocumentReferenceModel,
    EncounterModel,
    FHIRBundleModel,
    MedicationRequestModel,
    ObservationModel,
    PatientIdentifierModel,
    PatientModel,
    ProcedureModel,
)
from app.models.summary import ClinicalSummaryModel
from app.schemas.canonical import RecordStatus
from app.schemas.ingestion import ClinicalRecordResponse, RecordPaginationResponse
from app.schemas.patient import (
    LinkedFHIRResourceItem,
    PatientDetailResponse,
    PatientDomainCounts,
    PatientIdentifierItem,
    PatientListItem,
    PatientPaginationResponse,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/patients",
    tags=["Patient Management"],
    dependencies=[Depends(verify_api_key)],
)


@router.get(
    "",
    response_model=PatientPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="List and Search Patients",
    description="Returns a paginated list of canonical patients with optional text search across MRN and names.",
)
async def list_patients(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    query: Optional[str] = Query(default=None, description="Search query matching MRN, first name, or last name"),
    source_system: Optional[str] = Query(default=None, description="Filter by originating source system"),
    reconciliation_status: Optional[str] = Query(default=None, description="Filter by reconciliation status"),
    db: AsyncSession = Depends(get_db_session),
) -> PatientPaginationResponse:
    """Retrieve paginated patient directory with filter and query support."""
    conditions = []
    if source_system:
        conditions.append(func.lower(PatientModel.source_system) == source_system.lower())
    if reconciliation_status:
        conditions.append(PatientModel.reconciliation_status == reconciliation_status)
    if query and query.strip():
        q_term = f"%{query.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(PatientModel.mrn).like(q_term),
                func.lower(PatientModel.first_name).like(q_term),
                func.lower(PatientModel.last_name).like(q_term),
                func.lower(PatientModel.source_patient_id).like(q_term),
            )
        )

    # Count total matching patients
    count_stmt = select(func.count(PatientModel.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    count_res = await db.execute(count_stmt)
    total = count_res.scalar_one()

    total_pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size

    # Fetch paginated patients
    select_stmt = (
        select(PatientModel)
        .order_by(desc(PatientModel.created_at))
        .offset(offset)
        .limit(page_size)
    )
    if conditions:
        select_stmt = select_stmt.where(*conditions)

    patients_res = await db.execute(select_stmt)
    patients = list(patients_res.scalars().all())

    if not patients:
        return PatientPaginationResponse(
            items=[],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    p_ids = [p.id for p in patients]

    # Pre-fetch counts for records, bundles, and summaries in batch
    rec_count_stmt = (
        select(ClinicalRecordModel.patient_id, func.count(ClinicalRecordModel.id))
        .where(ClinicalRecordModel.patient_id.in_(p_ids))
        .group_by(ClinicalRecordModel.patient_id)
    )
    rec_counts = dict((await db.execute(rec_count_stmt)).all())

    bundle_count_stmt = (
        select(FHIRBundleModel.patient_id, func.count(FHIRBundleModel.id))
        .where(FHIRBundleModel.patient_id.in_(p_ids))
        .group_by(FHIRBundleModel.patient_id)
    )
    bundle_counts = dict((await db.execute(bundle_count_stmt)).all())

    summary_exists_stmt = (
        select(ClinicalSummaryModel.patient_id)
        .where(ClinicalSummaryModel.patient_id.in_(p_ids))
        .distinct()
    )
    summaries_set = set((await db.execute(summary_exists_stmt)).scalars().all())

    items = [
        PatientListItem(
            id=p.id,
            mrn=p.mrn,
            first_name=p.first_name,
            last_name=p.last_name,
            date_of_birth=p.date_of_birth,
            gender=p.administrative_gender,
            source_system=p.source_system,
            reconciliation_status=p.reconciliation_status,
            confidence_score=p.confidence_score,
            record_count=rec_counts.get(p.id, 0),
            bundle_count=bundle_counts.get(p.id, 0),
            has_summary=p.id in summaries_set,
            created_at=p.created_at,
        )
        for p in patients
    ]

    return PatientPaginationResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{patient_id}",
    response_model=PatientDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Patient Deep Dive",
    description="Retrieves comprehensive patient profile, domain counts, identifiers, latest bundle, and AI summary status.",
)
async def get_patient_detail(
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> PatientDetailResponse:
    """Fetch complete patient demographics, associated identifiers, and longitudinal record counts."""
    stmt = (
        select(PatientModel)
        .options(selectinload(PatientModel.identifiers))
        .where(PatientModel.id == patient_id)
    )
    result = await db.execute(stmt)
    patient = result.scalars().first()

    if not patient:
        # Check by MRN fallback if identifier was MRN
        mrn_stmt = (
            select(PatientModel)
            .options(selectinload(PatientModel.identifiers))
            .where(PatientModel.mrn == patient_id)
        )
        mrn_res = await db.execute(mrn_stmt)
        patient = mrn_res.scalars().first()

    if not patient:
        raise AppException(f"Patient '{patient_id}' not found", status_code=status.HTTP_404_NOT_FOUND)

    # Domain counts
    obs_cnt = (await db.execute(select(func.count(ObservationModel.id)).where(ObservationModel.patient_id == patient.id))).scalar_one()
    cond_cnt = (await db.execute(select(func.count(ConditionModel.id)).where(ConditionModel.patient_id == patient.id))).scalar_one()
    diag_cnt = (await db.execute(select(func.count(DiagnosticReportModel.id)).where(DiagnosticReportModel.patient_id == patient.id))).scalar_one()
    enc_cnt = (await db.execute(select(func.count(EncounterModel.id)).where(EncounterModel.patient_id == patient.id))).scalar_one()
    med_cnt = (await db.execute(select(func.count(MedicationRequestModel.id)).where(MedicationRequestModel.patient_id == patient.id))).scalar_one()
    proc_cnt = (await db.execute(select(func.count(ProcedureModel.id)).where(ProcedureModel.patient_id == patient.id))).scalar_one()
    doc_cnt = (await db.execute(select(func.count(DocumentReferenceModel.id)).where(DocumentReferenceModel.patient_id == patient.id))).scalar_one()
    rec_cnt = (await db.execute(select(func.count(ClinicalRecordModel.id)).where(ClinicalRecordModel.patient_id == patient.id))).scalar_one()

    domain_counts = PatientDomainCounts(
        observations=obs_cnt,
        conditions=cond_cnt,
        diagnostic_reports=diag_cnt,
        encounters=enc_cnt,
        medications=med_cnt,
        procedures=proc_cnt,
        document_references=doc_cnt,
        total_clinical_records=rec_cnt,
    )

    # Latest bundle info
    bundle_stmt = (
        select(FHIRBundleModel)
        .where(FHIRBundleModel.patient_id == patient.id)
        .order_by(desc(FHIRBundleModel.version))
        .limit(1)
    )
    latest_bundle = (await db.execute(bundle_stmt)).scalars().first()

    # Latest summary info
    summary_stmt = (
        select(ClinicalSummaryModel)
        .where(ClinicalSummaryModel.patient_id == patient.id)
        .order_by(desc(ClinicalSummaryModel.created_at))
        .limit(1)
    )
    latest_summary = (await db.execute(summary_stmt)).scalars().first()
    summary_preview = None
    if latest_summary:
        summary_preview = latest_summary.clinical_summary_text[:300] if latest_summary.clinical_summary_text else None

    identifiers = [
        PatientIdentifierItem(
            identifier_type=ident.identifier_type,
            value=ident.value,
            issuing_authority=ident.issuing_authority,
        )
        for ident in (patient.identifiers or [])
    ]

    return PatientDetailResponse(
        id=patient.id,
        mrn=patient.mrn,
        first_name=patient.first_name,
        middle_name=patient.middle_name,
        last_name=patient.last_name,
        date_of_birth=patient.date_of_birth,
        gender=patient.administrative_gender,
        source_system=patient.source_system,
        source_patient_id=patient.source_patient_id,
        reconciliation_status=patient.reconciliation_status,
        confidence_score=patient.confidence_score,
        contact_info=patient.contact_info,
        identifiers=identifiers,
        domain_counts=domain_counts,
        latest_bundle_id=latest_bundle.bundle_id if latest_bundle else None,
        latest_bundle_version=latest_bundle.version if latest_bundle else None,
        has_clinical_summary=latest_summary is not None,
        latest_summary_preview=summary_preview,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


@router.get(
    "/{patient_id}/records",
    response_model=RecordPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Patient Clinical Records",
    description="Returns paginated longitudinal clinical records and cleaned clinical text for a specific patient.",
)
async def get_patient_records(
    patient_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (NORMALIZED, REJECTED, etc.)"),
    db: AsyncSession = Depends(get_db_session),
) -> RecordPaginationResponse:
    """Return paginated clinical records for a specific patient."""
    # Resolve canonical patient (by id or mrn fallback)
    patient_stmt = select(PatientModel).where(PatientModel.id == patient_id)
    patient = (await db.execute(patient_stmt)).scalars().first()
    if not patient:
        mrn_stmt = select(PatientModel).where(PatientModel.mrn == patient_id)
        patient = (await db.execute(mrn_stmt)).scalars().first()

    canonical_patient_id = patient.id if patient else patient_id
    conditions = [ClinicalRecordModel.patient_id == canonical_patient_id]
    if status_filter:
        conditions.append(ClinicalRecordModel.status == status_filter.upper())

    count_stmt = select(func.count(ClinicalRecordModel.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    query_stmt = (
        select(ClinicalRecordModel)
        .where(*conditions)
        .order_by(desc(ClinicalRecordModel.record_date), desc(ClinicalRecordModel.created_at))
        .offset(offset)
        .limit(page_size)
    )
    items = list((await db.execute(query_stmt)).scalars().all())
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    formatted_items = [
        ClinicalRecordResponse(
            id=rec.id,
            job_id=rec.job_id,
            patient_id=rec.patient_id,
            record_type=rec.record_type,
            status=RecordStatus(rec.status),
            fingerprint=rec.fingerprint,
            source_record_id=rec.source_record_id,
            record_date=rec.record_date,
            cleaned_text=rec.cleaned_text,
            parsed_payload=rec.parsed_payload,
            validation_errors=rec.validation_errors,
            created_at=rec.created_at,
        )
        for rec in items
    ]

    return RecordPaginationResponse(
        items=formatted_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{patient_id}/fhir-resources",
    response_model=List[LinkedFHIRResourceItem],
    status_code=status.HTTP_200_OK,
    summary="Get Linked FHIR Resources for Patient",
    description="Returns actual conforming FHIR R4 resources linked to this patient from the stored bundle or domain models.",
)
async def get_patient_fhir_resources(
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> List[LinkedFHIRResourceItem]:
    """Retrieve actual linked FHIR resources (Observations, Conditions, DiagnosticReports, etc.) for a patient."""
    # Resolve canonical patient (by id or mrn fallback)
    patient_stmt = select(PatientModel).where(PatientModel.id == patient_id)
    patient = (await db.execute(patient_stmt)).scalars().first()
    if not patient:
        mrn_stmt = select(PatientModel).where(PatientModel.mrn == patient_id)
        patient = (await db.execute(mrn_stmt)).scalars().first()

    canonical_patient_id = patient.id if patient else patient_id
    canonical_mrn = patient.mrn if patient else patient_id

    # Check if a stored FHIR Bundle exists for this patient
    bundle_stmt = (
        select(FHIRBundleModel)
        .where(
            or_(
                FHIRBundleModel.patient_id == canonical_patient_id,
                FHIRBundleModel.patient_mrn == canonical_mrn,
            )
        )
        .order_by(desc(FHIRBundleModel.version), desc(FHIRBundleModel.created_at))
        .limit(1)
    )
    bundle_model = (await db.execute(bundle_stmt)).scalars().first()

    resources: List[LinkedFHIRResourceItem] = []
    seen_resource_ids = set()

    if bundle_model and bundle_model.bundle_json:
        entries = bundle_model.bundle_json.get("entry", [])
        for entry in entries:
            res = entry.get("resource", {})
            rtype = res.get("resourceType", "Resource")
            rid = res.get("id", "unknown")
            seen_resource_ids.add(rid)

            title = rtype
            date_val = None
            status_val = res.get("status")

            if rtype == "Patient":
                names = res.get("name", [{}])[0]
                family = names.get("family", "")
                given = " ".join(names.get("given", []))
                title = f"Patient Demographic: {given} {family}".strip()
                date_val = res.get("birthDate")
            elif rtype == "Observation":
                coding = res.get("code", {}).get("coding", [{}])[0]
                display = coding.get("display") or res.get("code", {}).get("text") or "Observation"
                val = ""
                if "valueQuantity" in res:
                    val = f"{res['valueQuantity'].get('value', '')} {res['valueQuantity'].get('unit', '')}".strip()
                elif "valueString" in res:
                    val = res.get("valueString", "")
                title = f"{display}: {val}" if val else display
                date_val = res.get("effectiveDateTime") or res.get("issued")
            elif rtype == "Condition":
                coding = res.get("code", {}).get("coding", [{}])[0]
                display = coding.get("display") or res.get("code", {}).get("text") or "Condition"
                title = f"Diagnosis: {display}"
                date_val = res.get("recordedDate") or res.get("onsetDateTime")
                status_val = res.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "active")
            elif rtype == "DiagnosticReport":
                coding = res.get("code", {}).get("coding", [{}])[0]
                display = coding.get("display") or res.get("code", {}).get("text") or "Diagnostic Report"
                title = f"Report: {display}"
                date_val = res.get("effectiveDateTime") or res.get("issued")
            elif rtype == "DocumentReference":
                coding = res.get("type", {}).get("coding", [{}])[0]
                display = coding.get("display") or "Clinical Note"
                title = f"Document: {display}"
                date_val = res.get("date")
            elif rtype == "Encounter":
                class_code = res.get("class", {}).get("code", "ambulatory")
                title = f"Encounter ({class_code})"
                date_val = res.get("period", {}).get("start")
            else:
                title = f"{rtype} ({rid})"

            details = {
                "id": rid,
                "resourceType": rtype,
                "status": status_val,
                "date": date_val,
                "bundle_id": bundle_model.bundle_id,
                "bundle_version": bundle_model.version,
            }
            resources.append(
                LinkedFHIRResourceItem(
                    resource_type=rtype,
                    id=rid,
                    title=title,
                    date=str(date_val) if date_val else None,
                    status=str(status_val) if status_val else None,
                    details=details,
                    raw_resource=res,
                )
            )

    # In addition, check domain models for any unbundled or freshly ingested items
    # 1. Observations
    obs_stmt = select(ObservationModel).where(ObservationModel.patient_id == canonical_patient_id).limit(50)
    observations = list((await db.execute(obs_stmt)).scalars().all())
    for obs in observations:
        if obs.id in seen_resource_ids:
            continue
        display = obs.display or obs.code
        val = f"{obs.value_numeric} {obs.unit or ''}".strip() if obs.value_numeric is not None else str(obs.value_string or "")
        title = f"Observation: {display} {val}".strip()
        resources.append(
            LinkedFHIRResourceItem(
                resource_type="Observation",
                id=obs.id,
                title=title,
                date=str(obs.effective_date) if obs.effective_date else None,
                status=obs.status,
                details={"encounter_id": obs.encounter_id, "category": obs.category},
                raw_resource={
                    "id": obs.id,
                    "resourceType": "Observation",
                    "status": obs.status,
                    "code": {"text": obs.display, "coding": [{"code": obs.code, "system": obs.code_system}]},
                    "valueQuantity": {"value": obs.value_numeric, "unit": obs.unit} if obs.value_numeric is not None else None,
                    "valueString": obs.value_string,
                },
            )
        )
        seen_resource_ids.add(obs.id)

    # 2. Conditions
    cond_stmt = select(ConditionModel).where(ConditionModel.patient_id == canonical_patient_id).limit(50)
    conditions = list((await db.execute(cond_stmt)).scalars().all())
    for cond in conditions:
        if cond.id in seen_resource_ids:
            continue
        display = cond.display or cond.code
        title = f"Diagnosis: {display}"
        resources.append(
            LinkedFHIRResourceItem(
                resource_type="Condition",
                id=cond.id,
                title=title,
                date=str(cond.recorded_date or cond.onset_date or ""),
                status=cond.clinical_status,
                details={"verification_status": cond.verification_status, "severity": cond.severity},
                raw_resource={
                    "id": cond.id,
                    "resourceType": "Condition",
                    "clinicalStatus": cond.clinical_status,
                    "verificationStatus": cond.verification_status,
                    "code": {"text": cond.display, "coding": [{"code": cond.code, "system": cond.code_system}]},
                },
            )
        )
        seen_resource_ids.add(cond.id)

    # 3. DiagnosticReports
    diag_stmt = select(DiagnosticReportModel).where(DiagnosticReportModel.patient_id == canonical_patient_id).limit(50)
    diagnostics = list((await db.execute(diag_stmt)).scalars().all())
    for diag in diagnostics:
        if diag.id in seen_resource_ids:
            continue
        display = diag.display or diag.code
        title = f"Diagnostic Report: {display}"
        resources.append(
            LinkedFHIRResourceItem(
                resource_type="DiagnosticReport",
                id=diag.id,
                title=title,
                date=str(diag.effective_date or ""),
                status=diag.status,
                details={"conclusion": diag.conclusion},
                raw_resource={
                    "id": diag.id,
                    "resourceType": "DiagnosticReport",
                    "status": diag.status,
                    "code": {"text": diag.display, "coding": [{"code": diag.code}]},
                    "conclusion": diag.conclusion,
                },
            )
        )
        seen_resource_ids.add(diag.id)

    return resources
