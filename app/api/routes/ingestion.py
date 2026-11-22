"""FastAPI endpoints for EHR Data Ingestion, Cleaning, and Normalization."""

import json
import tempfile
from datetime import timezone
from pathlib import Path
from typing import Any, List, Optional
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
import math
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.exceptions import AppException, ValidationException
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.ingestion.orchestrator import IngestionOrchestrator
from app.models.database import get_db_session, get_session_factory
from app.models.ingestion import IngestionJobModel
from app.repositories.clinical_record_repository import ClinicalRecordRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.schemas.canonical import JobStatus, MappingProfile, RecordStatus
from app.schemas.ingestion import (
    ClinicalRecordResponse,
    IngestionJobResponse,
    IngestionReportResponse,
    JSONIngestionRequest,
    JobPaginationResponse,
    PackageFileResponse,
    RecordPaginationResponse,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/ingestion",
    tags=["EHR Ingestion"],
    dependencies=[Depends(verify_api_key)],
)


def format_job_response(job) -> IngestionJobResponse:
    """Format SQLAlchemy IngestionJobModel to Pydantic IngestionJobResponse."""
    duration: Optional[float] = None
    if job.started_at and job.completed_at:
        s = job.started_at if job.started_at.tzinfo else job.started_at.replace(tzinfo=timezone.utc)
        c = job.completed_at if job.completed_at.tzinfo else job.completed_at.replace(tzinfo=timezone.utc)
        duration = (c - s).total_seconds()

    return IngestionJobResponse(
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


async def _run_background_ingestion(
    db_url: str,
    job_id: str,
    stream_or_data: Any,
    source_format: str,
    source_system: str,
    mapping_profile: Optional[MappingProfile],
) -> None:
    """Execute ingestion asynchronously in background task with dedicated session."""
    session_factory = get_session_factory(db_url)
    try:
        async with session_factory() as session:
            try:
                orchestrator = IngestionOrchestrator(session)
                norm_fmt = source_format.lower().lstrip(".")
                if norm_fmt in ["zip", "tar", "gz", "tgz"]:
                    await orchestrator.process_package(
                        job_id=job_id,
                        archive_path_or_bytes=stream_or_data,
                        source_system=source_system,
                        mapping_profile=mapping_profile,
                    )
                else:
                    await orchestrator.process_ingestion(
                        job_id=job_id,
                        stream_or_data=stream_or_data,
                        source_format=source_format,
                        source_system=source_system,
                        mapping_profile=mapping_profile,
                    )
            except Exception as exc:
                logger.error("Background ingestion failed for job %s: %s", job_id, exc, exc_info=True)
    finally:
        if hasattr(stream_or_data, "close"):
            try:
                stream_or_data.close()
            except Exception:
                pass


@router.post(
    "/upload",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and Ingest EHR File or Package",
    description="Uploads a JSON, CSV, Plain-Text, FHIR R4 Bundle/NDJSON, or multi-file ZIP/TAR package and processes it through the pipeline.",
)
async def upload_ehr_file(
    response: Response,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="EHR file or package (JSON, CSV, TXT, FHIR NDJSON, ZIP, TAR.GZ)"),
    source_system: str = Form("generic_ehr", description="Originating hospital or EHR system"),
    idempotency_key: Optional[str] = Form(None, description="Client idempotency key"),
    mapping_profile: Optional[str] = Form(None, description="Optional JSON mapping profile specification"),
    sync: bool = Query(default=True, description="Synchronous execution flag. If false, returns 202 Accepted and processes in background."),
    settings: Settings = Depends(get_current_settings),
    db: AsyncSession = Depends(get_db_session),
) -> IngestionJobResponse:
    """Securely stream in chunks, validate size, and ingest an uploaded EHR file or package."""
    if not file.filename:
        raise ValidationException("Uploaded file must have a valid filename.")

    fn_lower = file.filename.lower()
    if fn_lower.endswith(".tar.gz"):
        ext = ".tar.gz"
        fmt = "tar"
    elif fn_lower.endswith(".tgz"):
        ext = ".tgz"
        fmt = "tar"
    elif fn_lower.endswith(".ndjson"):
        ext = ".ndjson"
        fmt = "ndjson"
    elif fn_lower.endswith(".jsonl"):
        ext = ".jsonl"
        fmt = "ndjson"
    else:
        ext = Path(file.filename).suffix.lower()
        fmt = ext.lstrip(".")
        if fmt == "txt":
            fmt = "text"

    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationException(
            f"File extension '{ext}' is not supported.",
            details={"allowed_extensions": settings.ALLOWED_UPLOAD_EXTENSIONS},
        )

    chunk_size = 64 * 1024
    total_bytes = 0
    spooled_file = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024, mode="w+b")

    try:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
                raise ValidationException(
                    f"File size exceeds maximum permitted limit of {settings.MAX_UPLOAD_SIZE_BYTES} bytes.",
                    details={"size_bytes": total_bytes, "max_bytes": settings.MAX_UPLOAD_SIZE_BYTES},
                )
            spooled_file.write(chunk)

        if total_bytes == 0:
            raise ValidationException("Uploaded file is empty (0 bytes).")

        spooled_file.seek(0)

        orchestrator = IngestionOrchestrator(db)
        job, is_new = await orchestrator.create_or_get_job(
            source_format=fmt,
            source_system=source_system,
            idempotency_key=idempotency_key,
            metadata_json={"original_filename": Path(file.filename).name},
        )

        if not is_new:
            spooled_file.close()
            return format_job_response(job)

        parsed_mapping: Optional[MappingProfile] = None
        if mapping_profile:
            try:
                mp_dict = json.loads(mapping_profile)
                parsed_mapping = MappingProfile(**mp_dict)
            except Exception as exc:
                raise ValidationException(
                    "Invalid JSON mapping profile provided.",
                    details={"error": str(exc)},
                )

        if not sync:
            response.status_code = status.HTTP_202_ACCEPTED
            background_tasks.add_task(
                _run_background_ingestion,
                db_url=settings.sqlite_url,
                job_id=job.id,
                stream_or_data=spooled_file,
                source_format=fmt,
                source_system=source_system,
                mapping_profile=parsed_mapping,
            )
            return format_job_response(job)

        try:
            if fmt in ["zip", "tar", "tgz", "gz"]:
                processed_job = await orchestrator.process_package(
                    job_id=job.id,
                    archive_path_or_bytes=spooled_file,
                    source_system=source_system,
                    mapping_profile=parsed_mapping,
                )
            else:
                processed_job = await orchestrator.process_ingestion(
                    job_id=job.id,
                    stream_or_data=spooled_file,
                    source_format=fmt,
                    source_system=source_system,
                    mapping_profile=parsed_mapping,
                )
            return format_job_response(processed_job)
        finally:
            spooled_file.close()

    except Exception:
        spooled_file.close()
        raise


@router.post(
    "/json",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest JSON EHR Records",
    description="Directly submits a JSON payload containing patient records for cleaning and normalization.",
)
async def ingest_json_records(
    payload: JSONIngestionRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=True, description="Synchronous execution flag. If false, returns 202 Accepted and processes in background."),
    settings: Settings = Depends(get_current_settings),
    db: AsyncSession = Depends(get_db_session),
) -> IngestionJobResponse:
    """Ingest structured JSON EHR records directly via API request payload."""
    orchestrator = IngestionOrchestrator(db)

    job, is_new = await orchestrator.create_or_get_job(
        source_format="json",
        source_system=payload.source_system,
        idempotency_key=payload.idempotency_key,
        metadata_json={"record_count": len(payload.records)},
    )

    if not is_new:
        return format_job_response(job)

    if not sync:
        response.status_code = status.HTTP_202_ACCEPTED
        background_tasks.add_task(
            _run_background_ingestion,
            db_url=settings.sqlite_url,
            job_id=job.id,
            stream_or_data=payload.records,
            source_format="json",
            source_system=payload.source_system,
            mapping_profile=payload.mapping_profile,
        )
        return format_job_response(job)

    processed_job = await orchestrator.process_ingestion(
        job_id=job.id,
        stream_or_data=payload.records,
        source_format="json",
        source_system=payload.source_system,
        mapping_profile=payload.mapping_profile,
    )

    return format_job_response(processed_job)


@router.get(
    "/jobs",
    response_model=JobPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="List Ingestion Jobs",
    description="Retrieves a paginated list of all ingestion jobs with optional status filtering.",
)
async def list_ingestion_jobs(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (e.g. COMPLETED, FAILED)"),
    source_system: Optional[str] = Query(default=None, description="Filter by source system"),
    db: AsyncSession = Depends(get_db_session),
) -> JobPaginationResponse:
    """List paginated ingestion jobs ordered by created_at desc."""
    conditions = []
    if status_filter:
        conditions.append(IngestionJobModel.status == status_filter.upper())
    if source_system:
        conditions.append(func.lower(IngestionJobModel.source_system) == source_system.lower())

    count_stmt = select(func.count(IngestionJobModel.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    query_stmt = (
        select(IngestionJobModel)
        .order_by(desc(IngestionJobModel.created_at))
        .offset(offset)
        .limit(page_size)
    )
    if conditions:
        query_stmt = query_stmt.where(*conditions)

    jobs = list((await db.execute(query_stmt)).scalars().all())
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return JobPaginationResponse(
        items=[format_job_response(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Ingestion Job Status",
    description="Retrieves operational status, lifecycle state, and processing statistics for a job.",
)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> IngestionJobResponse:
    """Retrieve summary status and metrics for an ingestion job."""
    job_repo = IngestionJobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise AppException(f"Ingestion job '{job_id}' not found", status_code=status.HTTP_404_NOT_FOUND)
    return format_job_response(job)


@router.get(
    "/jobs/{job_id}/report",
    response_model=IngestionReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Ingestion Job Report",
    description="Generates a comprehensive audit and reconciliation report for an ingestion job.",
)
async def get_job_report(
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> IngestionReportResponse:
    """Generate detailed ingestion and reconciliation audit report."""
    orchestrator = IngestionOrchestrator(db)
    return await orchestrator.generate_report(job_id)


@router.get(
    "/jobs/{job_id}/records",
    response_model=RecordPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Paginated Ingestion Records",
    description="Retrieves paginated processed records associated with an ingestion job, with optional status filtering.",
)
async def get_job_records(
    job_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=500, description="Items per page"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (e.g. NORMALIZED, DUPLICATE, REJECTED)"),
    db: AsyncSession = Depends(get_db_session),
) -> RecordPaginationResponse:
    """Return paginated clinical records produced by an ingestion job."""
    job_repo = IngestionJobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise AppException(f"Ingestion job '{job_id}' not found", status_code=status.HTTP_404_NOT_FOUND)

    record_repo = ClinicalRecordRepository(db)
    items, total = await record_repo.get_records_by_job_id(
        job_id=job_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

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
    "/jobs/{job_id}/files",
    response_model=List[PackageFileResponse],
    summary="Get Ingestion Job Package Files",
    description="Retrieves the per-file execution status, domain, and record counts for an EHR export package import.",
)
async def get_job_package_files(
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> List[PackageFileResponse]:
    """Return all package file processing records associated with an ingestion job."""
    orchestrator = IngestionOrchestrator(db)
    files = await orchestrator.domain_repo.get_package_files_for_job(job_id)
    return [
        PackageFileResponse(
            id=f.id,
            job_id=f.job_id,
            file_path=f.file_path,
            domain=f.domain,
            format=f.format,
            status=f.status,
            total_records=f.total_records,
            successful_records=f.successful_records,
            rejected_records=f.rejected_records,
            error_message=f.error_message,
            created_at=f.created_at,
            completed_at=f.completed_at,
        )
        for f in files
    ]

