import time
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.models.database import get_db_session, get_session_factory
from app.schemas.summary import (
    BatchSummarizeRequest,
    BatchSummarizeResponse,
    ClinicalSummaryResponse,
    LLMHealthResponse,
    SummarizeBundleRequest,
    SummarizePatientRequest,
    SummaryTaskResponse,
)
from app.services.clinical_summarization_service import ClinicalSummarizationService
from app.services.summary_task_manager import summary_task_manager

logger = get_logger(__name__)

router = APIRouter(
    prefix="/ai",
    tags=["AI Clinical Summarization"],
    dependencies=[Depends(verify_api_key)],
)


async def _run_background_summary_generation(
    db_url: str,
    task_id: str,
    patient_id: str,
    bundle_id: Optional[str],
    force_refresh: bool,
    settings: Settings,
) -> None:
    """Execute clinical summary inference asynchronously in a background worker with isolated session."""
    session_factory = get_session_factory(db_url)
    start_time = time.perf_counter()
    try:
        async with session_factory() as session:
            await summary_task_manager.mark_processing(task_id, session=session)
            service = ClinicalSummarizationService(session=session, settings=settings)
            summary, was_cached, latency_ms = await service.summarize_patient(
                patient_id=patient_id,
                bundle_id=bundle_id,
                force_refresh=force_refresh,
            )
            await session.commit()
            total_ms = (time.perf_counter() - start_time) * 1000.0
            await summary_task_manager.mark_completed(
                task_id=task_id,
                summary=summary,
                latency_ms=total_ms,
                session=session,
            )
            logger.info(
                "Background summary task [%s] for patient [%s] completed in %.2fs (was_cached=%s)",
                task_id,
                patient_id,
                total_ms / 1000.0,
                was_cached,
            )
    except Exception as exc:
        total_ms = (time.perf_counter() - start_time) * 1000.0
        logger.exception("Background summary task [%s] for patient [%s] failed: %s", task_id, patient_id, exc)
        try:
            async with session_factory() as session:
                await summary_task_manager.mark_failed(
                    task_id=task_id,
                    error_message=str(exc),
                    latency_ms=total_ms,
                    session=session,
                )
        except Exception:
            await summary_task_manager.mark_failed(
                task_id=task_id,
                error_message=str(exc),
                latency_ms=total_ms,
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
    response_model=Union[ClinicalSummaryResponse, SummaryTaskResponse],
    status_code=status.HTTP_200_OK,
    summary="Summarize Persisted Patient Records",
    description="Loads the patient's normalized FHIR Bundle from storage and generates or returns a cached clinical summary. Supports asynchronous execution via sync=false.",
)
async def summarize_stored_patient(
    response: Response,
    background_tasks: BackgroundTasks,
    patient_id: str,
    bundle_id: Optional[str] = Query(default=None, description="Optional bundle ID to summarize; defaults to latest"),
    force_refresh: bool = Query(default=False, description="Force re-inference bypassing the persistent cache"),
    sync: bool = Query(default=True, description="Synchronous execution flag. If false, returns 202 Accepted and processes in background."),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> Union[ClinicalSummaryResponse, SummaryTaskResponse]:
    """Generate or retrieve clinical summary for a stored patient (sync or async)."""
    if not sync:
        response.status_code = status.HTTP_202_ACCEPTED
        task_id, is_new = await summary_task_manager.create_or_get_task(
            patient_id=patient_id,
            bundle_id=bundle_id,
            force_refresh=force_refresh,
            session=db,
        )
        if is_new:
            background_tasks.add_task(
                _run_background_summary_generation,
                db_url=settings.sqlite_url,
                task_id=task_id,
                patient_id=patient_id,
                bundle_id=bundle_id,
                force_refresh=force_refresh,
                settings=settings,
            )
        task_data = (await summary_task_manager.get_task(task_id, session=db)) or {}
        return SummaryTaskResponse(
            task_id=task_id,
            patient_id=patient_id,
            status=task_data.get("status", "PENDING"),
            message="AI clinical summary generation scheduled in background worker.",
            created_at=task_data.get("created_at"),
        )

    service = ClinicalSummarizationService(session=db, settings=settings)
    summary, _, _ = await service.summarize_patient(
        patient_id=patient_id,
        bundle_id=bundle_id,
        force_refresh=force_refresh,
    )
    await db.commit()
    return summary


@router.post(
    "/summarize/patient/{patient_id}/regenerate",
    response_model=SummaryTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Asynchronously Regenerate Patient Clinical Summary",
    description="Bypasses inference cache and asynchronously regenerates a fresh clinical summary in a background worker.",
)
async def regenerate_patient_summary_async(
    response: Response,
    background_tasks: BackgroundTasks,
    patient_id: str,
    bundle_id: Optional[str] = Query(default=None, description="Optional bundle ID to summarize; defaults to latest"),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> SummaryTaskResponse:
    """Asynchronously regenerate clinical summary for a patient."""
    response.status_code = status.HTTP_202_ACCEPTED
    task_id, is_new = await summary_task_manager.create_or_get_task(
        patient_id=patient_id,
        bundle_id=bundle_id,
        force_refresh=True,  # Regeneration forces fresh inference
        session=db,
    )
    if is_new:
        background_tasks.add_task(
            _run_background_summary_generation,
            db_url=settings.sqlite_url,
            task_id=task_id,
            patient_id=patient_id,
            bundle_id=bundle_id,
            force_refresh=True,
            settings=settings,
        )
    task_data = (await summary_task_manager.get_task(task_id, session=db)) or {}
    return SummaryTaskResponse(
        task_id=task_id,
        patient_id=patient_id,
        status=task_data.get("status", "PENDING"),
        message="AI clinical summary regeneration scheduled in background worker.",
        created_at=task_data.get("created_at"),
    )


@router.get(
    "/summarize/status/{patient_id}",
    response_model=SummaryTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Asynchronous Summary Generation Status",
    description="Checks the real-time status and result of background summary generation or regeneration for a patient.",
)
async def get_summary_generation_status(
    patient_id: str,
    task_id: Optional[str] = Query(default=None, description="Optional specific task ID to inspect"),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> SummaryTaskResponse:
    """Check status of asynchronous clinical summary generation."""
    task_info = None
    if task_id:
        task_info = await summary_task_manager.get_task(task_id, session=db)
    if not task_info:
        task_info = await summary_task_manager.get_latest_task_for_patient(patient_id, session=db)

    if task_info:
        return SummaryTaskResponse(
            task_id=task_info["task_id"],
            patient_id=task_info["patient_id"],
            status=task_info["status"],
            message=task_info.get("message", f"Task status: {task_info['status']}"),
            created_at=task_info["created_at"],
            started_at=task_info.get("started_at"),
            completed_at=task_info.get("completed_at"),
            duration_seconds=task_info.get("duration_seconds"),
            summary=task_info.get("summary"),
            error_message=task_info.get("error_message"),
        )

    service = ClinicalSummarizationService(session=db, settings=settings)
    latest_model = await service.summary_repo.get_latest_by_patient_id(patient_id)
    if latest_model and latest_model.summary_json:
        summary_obj = ClinicalSummaryResponse.model_validate(latest_model.summary_json)
        return SummaryTaskResponse(
            task_id=latest_model.id,
            patient_id=patient_id,
            status="COMPLETED",
            message="Existing clinical summary available.",
            created_at=latest_model.created_at,
            completed_at=latest_model.updated_at,
            duration_seconds=round(latest_model.execution_time_ms / 1000.0, 2),
            summary=summary_obj,
        )

    raise AppException(
        f"No summary task or existing summary found for patient '{patient_id}'",
        status_code=status.HTTP_404_NOT_FOUND,
    )



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
