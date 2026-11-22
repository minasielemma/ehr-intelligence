"""FastAPI router for clinical operations dashboard analytics and operational metrics."""

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_cached_stats: Optional[Tuple[float, Any]] = None
_cache_lock = asyncio.Lock()
CACHE_TTL_SECONDS = 15.0

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.models.database import get_db_session
from app.models.ingestion import (
    AllergyIntoleranceModel,
    ClinicalRecordModel,
    ConditionModel,
    DiagnosticReportModel,
    DocumentReferenceModel,
    EncounterModel,
    FHIRBundleModel,
    ImmunizationModel,
    IngestionJobModel,
    MedicationRequestModel,
    ObservationModel,
    PatientModel,
    ProcedureModel,
)
from app.models.summary import ClinicalSummaryModel
from app.schemas.dashboard import (
    DashboardStatsResponse,
    DomainDistribution,
    RecentJobSummary,
    RecentPatientSummary,
    StatusBreakdown,
)
from app.search.vector_store import get_vector_store

logger = get_logger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard Analytics"],
    dependencies=[Depends(verify_api_key)],
)


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Aggregated Dashboard Analytics",
    description=(
        "Retrieves real database-derived analytics, resource counts across all clinical domains, "
        "job execution breakdowns, vector store metrics, and recent activity."
    ),
)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_current_settings),
) -> DashboardStatsResponse:
    """Calculate and return operational KPI metrics directly from persistent structured storage."""
    global _cached_stats
    now_ts = time.time()
    if _cached_stats is not None:
        cached_ts, cached_obj = _cached_stats
        if now_ts - cached_ts < CACHE_TTL_SECONDS:
            return cached_obj

    async with _cache_lock:
        if _cached_stats is not None:
            cached_ts, cached_obj = _cached_stats
            if now_ts - cached_ts < CACHE_TTL_SECONDS:
                return cached_obj

        # 1. Consolidated High-Level Entity Counts (Single round trip)
    kpi_stmt = select(
        select(func.count(PatientModel.id)).scalar_subquery().label("total_patients"),
        select(func.count(ClinicalRecordModel.id)).scalar_subquery().label("total_records"),
        select(func.count(FHIRBundleModel.id)).scalar_subquery().label("total_bundles"),
        select(func.coalesce(func.sum(FHIRBundleModel.resource_count), 0)).scalar_subquery().label("total_fhir_resources"),
        select(func.count(DiagnosticReportModel.id)).scalar_subquery().label("total_diagnostic_reports"),
        select(func.count(ClinicalSummaryModel.id)).scalar_subquery().label("total_summaries"),
        select(func.count(IngestionJobModel.id)).scalar_subquery().label("total_jobs"),
    )
    kpi_row = (await db.execute(kpi_stmt)).one()

    total_patients = int(kpi_row.total_patients)
    total_records = int(kpi_row.total_records)
    total_bundles = int(kpi_row.total_bundles)
    total_fhir_resources = int(kpi_row.total_fhir_resources)
    total_diagnostic_reports = int(kpi_row.total_diagnostic_reports)
    total_summaries = int(kpi_row.total_summaries)
    total_jobs = int(kpi_row.total_jobs)

    # 2. Vector Store Count (Offloaded to worker thread pool to prevent blocking async event loop)
    active_vectors = 0
    try:
        v_store = get_vector_store(settings)
        active_vectors = await asyncio.to_thread(v_store.count)
    except Exception as exc:
        logger.warning("Could not read vector store count: %s", exc)

    # 3. Jobs by Status
    job_status_stmt = (
        select(IngestionJobModel.status, func.count(IngestionJobModel.id))
        .group_by(IngestionJobModel.status)
    )
    job_status_res = await db.execute(job_status_stmt)
    jobs_by_status = [
        StatusBreakdown(status=row[0] or "UNKNOWN", count=row[1])
        for row in job_status_res.all()
    ]

    # 4. Records by Status
    rec_status_stmt = (
        select(ClinicalRecordModel.status, func.count(ClinicalRecordModel.id))
        .group_by(ClinicalRecordModel.status)
    )
    rec_status_res = await db.execute(rec_status_stmt)
    records_by_status = [
        StatusBreakdown(status=row[0] or "UNKNOWN", count=row[1])
        for row in rec_status_res.all()
    ]

    # 5. Consolidated Domain distribution counts (Single round trip)
    domain_stmt = select(
        select(func.count(ObservationModel.id)).scalar_subquery().label("Observation"),
        select(func.count(ConditionModel.id)).scalar_subquery().label("Condition"),
        select(func.count(DiagnosticReportModel.id)).scalar_subquery().label("DiagnosticReport"),
        select(func.count(EncounterModel.id)).scalar_subquery().label("Encounter"),
        select(func.count(MedicationRequestModel.id)).scalar_subquery().label("MedicationRequest"),
        select(func.count(ProcedureModel.id)).scalar_subquery().label("Procedure"),
        select(func.count(AllergyIntoleranceModel.id)).scalar_subquery().label("AllergyIntolerance"),
        select(func.count(ImmunizationModel.id)).scalar_subquery().label("Immunization"),
        select(func.count(DocumentReferenceModel.id)).scalar_subquery().label("DocumentReference"),
    )
    domain_row = (await db.execute(domain_stmt)).one()

    domain_counts: Dict[str, int] = {
        "Observation": int(domain_row.Observation),
        "Condition": int(domain_row.Condition),
        "DiagnosticReport": int(domain_row.DiagnosticReport),
        "Encounter": int(domain_row.Encounter),
        "MedicationRequest": int(domain_row.MedicationRequest),
        "Procedure": int(domain_row.Procedure),
        "AllergyIntolerance": int(domain_row.AllergyIntolerance),
        "Immunization": int(domain_row.Immunization),
        "DocumentReference": int(domain_row.DocumentReference),
    }
    total_domain_items = sum(domain_counts.values())

    domain_distribution: List[DomainDistribution] = []
    denom = total_domain_items if total_domain_items > 0 else 1
    for name, count in domain_counts.items():
        pct = round((count / denom) * 100, 1)
        domain_distribution.append(DomainDistribution(name=name, count=count, percentage=pct))

    # Sort descending by count
    domain_distribution.sort(key=lambda d: d.count, reverse=True)

    # 6. Recent Jobs (up to 8)
    recent_jobs_stmt = (
        select(IngestionJobModel)
        .order_by(desc(IngestionJobModel.created_at))
        .limit(8)
    )
    recent_jobs_res = await db.execute(recent_jobs_stmt)
    recent_jobs: List[RecentJobSummary] = []
    for job in recent_jobs_res.scalars().all():
        duration = None
        if job.started_at and job.completed_at:
            s = job.started_at if job.started_at.tzinfo else job.started_at.replace(tzinfo=timezone.utc)
            c = job.completed_at if job.completed_at.tzinfo else job.completed_at.replace(tzinfo=timezone.utc)
            duration = round((c - s).total_seconds(), 2)

        recent_jobs.append(
            RecentJobSummary(
                id=job.id,
                source_system=job.source_system,
                source_format=job.source_format,
                status=job.status,
                total_records=job.total_records,
                successful_records=job.successful_records,
                rejected_records=job.rejected_records,
                created_at=job.created_at,
                duration_seconds=duration,
            )
        )

    # 7. Recent Patients (up to 8)
    recent_patients_stmt = (
        select(PatientModel)
        .order_by(desc(PatientModel.created_at))
        .limit(8)
    )
    recent_patients_res = await db.execute(recent_patients_stmt)
    recent_patients = [
        RecentPatientSummary(
            id=p.id,
            mrn=p.mrn,
            first_name=p.first_name,
            last_name=p.last_name,
            date_of_birth=p.date_of_birth,
            gender=p.administrative_gender,
            source_system=p.source_system,
            reconciliation_status=p.reconciliation_status,
            created_at=p.created_at,
        )
        for p in recent_patients_res.scalars().all()
    ]

    resp = DashboardStatsResponse(
        total_patients=total_patients,
        total_records=total_records,
        total_fhir_bundles=total_bundles,
        total_fhir_resources=total_fhir_resources if total_fhir_resources > 0 else total_domain_items,
        total_diagnostic_reports=total_diagnostic_reports,
        total_clinical_summaries=total_summaries,
        total_jobs=total_jobs,
        active_vectors=active_vectors,
        jobs_by_status=jobs_by_status,
        records_by_status=records_by_status,
        domain_distribution=domain_distribution,
        recent_jobs=recent_jobs,
        recent_patients=recent_patients,
        system_status="healthy",
        timestamp=datetime.now(timezone.utc),
    )
    _cached_stats = (now_ts, resp)
    return resp
