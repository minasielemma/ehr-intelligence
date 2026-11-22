"""API request and response schemas for the EHR Ingestion endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.canonical import (
    AuditRecord,
    CanonicalPatient,
    JobStatus,
    MappingProfile,
    ReconciliationStatus,
    RecordStatus,
)


class JSONIngestionRequest(BaseModel):
    """Payload for submitting structured EHR JSON records directly to the API."""
    model_config = ConfigDict(extra="ignore")

    source_system: str = Field(default="generic_ehr", description="Issuing source EHR system")
    records: List[Dict[str, Any]] = Field(..., min_length=1, description="List of raw EHR records to ingest")
    idempotency_key: Optional[str] = Field(default=None, max_length=128, description="Optional client idempotency key")
    mapping_profile: Optional[MappingProfile] = Field(default=None, description="Custom field mapping specification")


class IngestionJobResponse(BaseModel):
    """Summary of an ingestion job lifecycle state and operational statistics."""
    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: JobStatus
    source_format: str
    source_system: str
    total_records: int
    successful_records: int
    rejected_records: int
    duplicate_records: int
    warning_records: int
    conflict_records: int
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class ClinicalRecordResponse(BaseModel):
    """Public representation of a processed EHR record."""
    model_config = ConfigDict(extra="ignore")

    id: str
    job_id: str
    patient_id: Optional[str] = None
    record_type: str
    status: RecordStatus
    fingerprint: str
    source_record_id: Optional[str] = None
    record_date: Optional[str] = None
    cleaned_text: Optional[str] = None
    parsed_payload: Optional[Dict[str, Any]] = None
    validation_errors: Optional[List[Dict[str, Any]]] = None
    created_at: datetime


class PackageFileResponse(BaseModel):
    """Execution status and metrics for an individual file within an EHR export package."""
    model_config = ConfigDict(extra="ignore")

    id: str
    job_id: str
    file_path: str
    domain: str
    format: str
    status: str
    total_records: int
    successful_records: int
    rejected_records: int
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class IngestionReportResponse(BaseModel):
    """Detailed post-ingestion audit report describing job metrics, domain counts, and anomalies."""
    model_config = ConfigDict(extra="ignore")

    job: IngestionJobResponse
    reconciliation_summary: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts of patient records by reconciliation status (MATCHED, NEW_PATIENT, etc.)",
    )
    duplicate_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Breakdown of detected duplicate records vs valid updates",
    )
    warnings: List[str] = Field(default_factory=list, description="Aggregated non-fatal warnings")
    recent_audit_events: List[AuditRecord] = Field(
        default_factory=list, description="Sample of per-record audit logs for this job"
    )
    domain_summary: Dict[str, int] = Field(
        default_factory=dict,
        description="Record counts across persisted clinical, administrative, and financial domains",
    )
    referential_integrity: Dict[str, Any] = Field(
        default_factory=dict,
        description="Referential integrity audit metrics and orphan detection summary",
    )
    package_files: List[PackageFileResponse] = Field(
        default_factory=list,
        description="Per-file processing status and counts for multi-file export packages",
    )


class RecordPaginationResponse(BaseModel):
    """Paginated list of processed records for an ingestion job."""
    model_config = ConfigDict(extra="ignore")

    items: List[ClinicalRecordResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class JobPaginationResponse(BaseModel):
    """Paginated list of ingestion jobs."""
    model_config = ConfigDict(extra="ignore")

    items: List[IngestionJobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

