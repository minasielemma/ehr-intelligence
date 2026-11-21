"""FastAPI endpoints for AI-Powered Clinical Summarization, Inference Caching, and Provider Diagnostics."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.models.database import get_db_session
from app.schemas.summary import (
    BatchSummarizeRequest,
    BatchSummarizeResponse,
    ClinicalSummaryResponse,
    LLMHealthResponse,
    SummarizeBundleRequest,
    SummarizePatientRequest,
)
from app.services.clinical_summarization_service import ClinicalSummarizationService

logger = get_logger(__name__)

router = APIRouter(
    prefix="/ai",
    tags=["AI Clinical Summarization"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/summarize/bundle",
    response_model=ClinicalSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Summarize FHIR R4 Bundle Payload",
    description="Generates a structured, evidence-grounded clinical summary from a validated HL7 FHIR R4 Bundle JSON payload.",
)
async def summarize_fhir_bundle(
    payload: SummarizeBundleRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> ClinicalSummaryResponse:
    """Summarize a provided FHIR R4 Bundle directly."""
    service = ClinicalSummarizationService(session=db, settings=settings)
    summary, _, _ = await service.summarize_bundle(
        bundle_data=payload.bundle,
        force_refresh=payload.force_refresh,
    )
    await db.commit()
    return summary


@router.post(
    "/summarize/patient/{patient_id}",
    response_model=ClinicalSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Summarize Persisted Patient Records",
    description="Loads the patient's normalized FHIR Bundle from storage and generates or returns a cached clinical summary.",
)
async def summarize_stored_patient(
    patient_id: str,
    bundle_id: Optional[str] = Query(default=None, description="Optional bundle ID to summarize; defaults to latest"),
    force_refresh: bool = Query(default=False, description="Force re-inference bypassing the persistent cache"),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> ClinicalSummaryResponse:
    """Generate or retrieve clinical summary for a stored patient."""
    service = ClinicalSummarizationService(session=db, settings=settings)
    summary, _, _ = await service.summarize_patient(
        patient_id=patient_id,
        bundle_id=bundle_id,
        force_refresh=force_refresh,
    )
    await db.commit()
    return summary


@router.post(
    "/summarize/batch",
    response_model=BatchSummarizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch Summarize Multiple Patients",
    description="Processes multiple patients with strict error isolation, ensuring an individual failure never halts processing of others.",
)
async def summarize_batch_patients(
    payload: BatchSummarizeRequest,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> BatchSummarizeResponse:
    """Execute batch summarization across multiple patient IDs."""
    service = ClinicalSummarizationService(session=db, settings=settings)
    resp = await service.summarize_batch(
        patient_ids=payload.patient_ids,
        force_refresh=payload.force_refresh,
    )
    await db.commit()
    return resp


@router.get(
    "/summary/{patient_id}",
    response_model=ClinicalSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Cached Clinical Summary",
    description="Retrieves the most recent cached clinical summary for a patient without triggering LLM inference.",
)
async def get_patient_summary(
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> ClinicalSummaryResponse:
    """Retrieve the latest cached clinical summary for a patient."""
    service = ClinicalSummarizationService(session=db, settings=settings)
    latest_model = await service.summary_repo.get_latest_by_patient_id(patient_id)
    if not latest_model or not latest_model.summary_json:
        raise AppException(
            f"No clinical summary found for patient '{patient_id}'. Trigger generation via POST /api/v1/ai/summarize/patient/{patient_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    ttl = settings.SUMMARY_CACHE_TTL_SECONDS
    if ttl is not None and ttl > 0:
        from datetime import datetime, timezone
        now_dt = datetime.now(timezone.utc)
        created = latest_model.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (now_dt - created).total_seconds()
        if age_seconds > ttl:
            logger.info("Summary [%s] for patient [%s] expired (age: %.1fs > ttl: %ds)", latest_model.id, patient_id, age_seconds, ttl)
            await service.summary_repo.delete_by_cache_key(latest_model.cache_key)
            await db.commit()
            raise AppException(
                f"Clinical summary for patient '{patient_id}' has expired. Trigger generation via POST /api/v1/ai/summarize/patient/{patient_id}",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    return ClinicalSummaryResponse.model_validate(latest_model.summary_json)



@router.delete(
    "/cache/{patient_id}",
    status_code=status.HTTP_200_OK,
    summary="Invalidate Patient Summary Cache",
    description="Purges all cached clinical summaries for a specific patient to ensure subsequent requests trigger fresh inference.",
)
async def invalidate_summary_cache(
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> Dict[str, Any]:
    """Invalidate summary cache for a patient."""
    service = ClinicalSummarizationService(session=db, settings=settings)
    deleted_count = await service.cache_manager.invalidate_patient_cache(patient_id)
    await db.commit()
    return {
        "patient_id": patient_id,
        "invalidated": True,
        "deleted_records": deleted_count,
        "message": f"Successfully invalidated {deleted_count} cached summary records for patient {patient_id}",
    }


@router.get(
    "/health",
    response_model=LLMHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="LLM Provider Diagnostics and Health",
    description="Tests connectivity, response latency, and model availability for the active LLM provider.",
)
async def check_llm_provider_health(
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> LLMHealthResponse:
    """Perform live health check against the active LLM provider."""
    service = ClinicalSummarizationService(session=db, settings=settings)
    health_dict = await service.provider.check_health()
    return LLMHealthResponse.model_validate(health_dict)
