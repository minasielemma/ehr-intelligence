"""FastAPI endpoints for HL7 FHIR R4 Normalization, Conformance Validation, and Bundle Storage."""

import math
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.fhir.validator import FHIRValidator
from app.models.database import get_db_session
from app.repositories.fhir_bundle_repository import FHIRBundleRepository
from app.schemas.fhir import (
    FHIRBundlePaginationResponse,
    FHIRBundleSummary,
    FHIRNormalizationRequest,
    FHIRNormalizationResponse,
    FHIRValidationReport,
    FHIRValidationRequest,
)
from app.services.fhir_normalization_service import FHIRNormalizationService

logger = get_logger(__name__)

router = APIRouter(
    prefix="/fhir",
    tags=["FHIR R4 Normalization"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/normalize",
    response_model=FHIRNormalizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Normalize Cleaned EHR Payload into FHIR R4 Bundle",
    description="Transforms canonical patient demographics and associated clinical records into a validated HL7 FHIR R4 Bundle.",
)
async def normalize_payload(
    payload: FHIRNormalizationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> FHIRNormalizationResponse:
    """Transform canonical patient and record data into a validated FHIR R4 Bundle."""
    service = FHIRNormalizationService(db)

    if payload.patient_id and not payload.patient:
        return await service.normalize_db_patient(
            patient_id=payload.patient_id,
            bundle_type=payload.bundle_type,
            save_to_store=payload.save_to_store,
        )

    if not payload.patient:
        raise AppException("Either 'patient' payload or 'patient_id' must be provided", status_code=400)

    return await service.normalize_patient_bundle(
        patient=payload.patient,
        records=payload.records,
        bundle_type=payload.bundle_type,
        save_to_store=payload.save_to_store,
    )


@router.post(
    "/normalize/patient/{patient_id}",
    response_model=FHIRNormalizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Normalize Database Patient into FHIR R4 Bundle",
    description="Loads reconciled patient and all longitudinal clinical records from the database and generates a validated FHIR R4 Bundle.",
)
async def normalize_patient(
    patient_id: str,
    bundle_type: str = Query(default="collection", description="Target Bundle type: collection or transaction"),
    save_to_store: bool = Query(default=True, description="Persist validated bundle to SQLite and disk storage"),
    db: AsyncSession = Depends(get_db_session),
) -> FHIRNormalizationResponse:
    """Normalize a stored database patient and records into a validated FHIR Bundle."""
    service = FHIRNormalizationService(db)
    return await service.normalize_db_patient(
        patient_id=patient_id,
        bundle_type=bundle_type,
        save_to_store=save_to_store,
    )


@router.post(
    "/normalize/job/{job_id}",
    response_model=List[FHIRNormalizationResponse],
    status_code=status.HTTP_200_OK,
    summary="Batch Normalize Ingestion Job to FHIR Bundles",
    description="Normalizes all reconciled patients and clinical records associated with an ingestion job into patient-centric FHIR R4 Bundles with per-patient isolation.",
)
async def normalize_job_patients(
    job_id: str,
    bundle_type: str = Query(default="collection", description="Target Bundle type: collection or transaction"),
    save_to_store: bool = Query(default=True, description="Persist validated bundles to storage"),
    db: AsyncSession = Depends(get_db_session),
) -> List[FHIRNormalizationResponse]:
    """Batch-normalize all patients and records from an ingestion job into isolated FHIR Bundles."""
    service = FHIRNormalizationService(db)
    return await service.normalize_job(
        job_id=job_id,
        bundle_type=bundle_type,
        save_to_store=save_to_store,
    )


@router.post(
    "/validate",
    response_model=FHIRValidationReport,
    status_code=status.HTTP_200_OK,
    summary="Validate FHIR Resource or Bundle",
    description="Performs deep FHIR R4 schema, primitive types, cardinality, and referential integrity validation on an arbitrary FHIR payload.",
)
async def validate_fhir_payload(
    payload: FHIRValidationRequest,
) -> FHIRValidationReport:
    """Validate any FHIR R4 resource or Bundle and return a detailed conformance report."""
    res = payload.resource
    res_type = res.get("resourceType")
    if res_type == "Bundle":
        return FHIRValidator.validate_bundle_detailed(
            bundle_data=res,
            expected_patient_id=payload.patient_identifier,
        )

    # Individual resource validation
    issues = FHIRValidator.validate_resource_detailed(res)
    error_cnt = sum(1 for i in issues if i.severity.value == "ERROR")
    warn_cnt = sum(1 for i in issues if i.severity.value == "WARNING")
    info_cnt = sum(1 for i in issues if i.severity.value == "INFORMATION")

    from app.schemas.fhir import ValidationStatus
    status_val = ValidationStatus.INVALID if error_cnt > 0 else (ValidationStatus.WARNING if warn_cnt > 0 else ValidationStatus.VALID)

    return FHIRValidationReport(
        patient_identifier=payload.patient_identifier or res.get("id", "UNKNOWN"),
        bundle_id=None,
        status=status_val,
        total_resources=1,
        valid_resources=0 if error_cnt > 0 else 1,
        invalid_resources=1 if error_cnt > 0 else 0,
        error_count=error_cnt,
        warning_count=warn_cnt,
        info_count=info_cnt,
        issues=issues,
    )


@router.get(
    "/bundles/{bundle_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Retrieve Stored FHIR R4 Bundle",
    description="Retrieves a persisted FHIR R4 Bundle JSON by its unique bundle identifier.",
)
async def get_bundle_by_id(
    bundle_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve full FHIR R4 Bundle JSON by bundle ID."""
    repo = FHIRBundleRepository(db)
    model = await repo.get_by_bundle_id(bundle_id)
    if not model:
        raise AppException(f"FHIR Bundle '{bundle_id}' not found", status_code=status.HTTP_404_NOT_FOUND)
    return model.bundle_json


@router.get(
    "/bundles/{bundle_id}/report",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Retrieve Bundle Validation Report",
    description="Retrieves the structured validation report recorded when the bundle was validated.",
)
async def get_bundle_report(
    bundle_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve validation report for a stored FHIR Bundle."""
    repo = FHIRBundleRepository(db)
    model = await repo.get_by_bundle_id(bundle_id)
    if not model:
        raise AppException(f"FHIR Bundle '{bundle_id}' not found", status_code=status.HTTP_404_NOT_FOUND)
    if not model.validation_report_json:
        raise AppException(f"Validation report not available for bundle '{bundle_id}'", status_code=status.HTTP_404_NOT_FOUND)
    return model.validation_report_json


@router.get(
    "/bundles/patient/{patient_id}",
    response_model=List[FHIRBundleSummary],
    status_code=status.HTTP_200_OK,
    summary="Retrieve FHIR Bundles for Patient",
    description="Retrieves stored FHIR Bundle summaries for a patient ID, ordered by version descending.",
)
async def get_patient_bundles(
    patient_id: str,
    latest: bool = Query(default=True, description="Return only the latest version"),
    db: AsyncSession = Depends(get_db_session),
) -> List[FHIRBundleSummary]:
    """Retrieve bundle summaries for a given patient ID."""
    repo = FHIRBundleRepository(db)
    models = await repo.get_by_patient_id(patient_id=patient_id, latest_only=latest)
    return [
        FHIRBundleSummary(
            id=m.id,
            bundle_id=m.bundle_id,
            patient_id=m.patient_id,
            patient_mrn=m.patient_mrn,
            bundle_type=m.bundle_type,
            version=m.version,
            status=m.status,
            resource_count=m.resource_count,
            content_hash=m.content_hash,
            file_path=m.file_path,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in models
    ]


@router.get(
    "/bundles",
    response_model=FHIRBundlePaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="List Stored FHIR Bundles",
    description="Returns a paginated list of persisted FHIR Bundle summaries with optional status filtering.",
)
async def list_stored_bundles(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=500, description="Items per page"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (e.g. VALID, WARNING)"),
    db: AsyncSession = Depends(get_db_session),
) -> FHIRBundlePaginationResponse:
    """List paginated FHIR Bundles."""
    repo = FHIRBundleRepository(db)
    skip = (page - 1) * page_size
    items, total = await repo.list_bundles(skip=skip, limit=page_size, status_filter=status_filter)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    bundle_summaries = [
        FHIRBundleSummary(
            id=m.id,
            bundle_id=m.bundle_id,
            patient_id=m.patient_id,
            patient_mrn=m.patient_mrn,
            bundle_type=m.bundle_type,
            version=m.version,
            status=m.status,
            resource_count=m.resource_count,
            content_hash=m.content_hash,
            file_path=m.file_path,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in items
    ]
    return FHIRBundlePaginationResponse(
        items=bundle_summaries,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
