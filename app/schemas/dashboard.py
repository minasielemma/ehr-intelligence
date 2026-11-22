"""Pydantic schemas for platform dashboard analytics and operational metrics."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DomainDistribution(BaseModel):
    """Distribution of clinical data across normalized healthcare domains."""
    name: str = Field(..., description="Healthcare domain or FHIR resource type")
    count: int = Field(..., description="Total count of records in this domain")
    percentage: float = Field(..., description="Percentage of total clinical records")


class StatusBreakdown(BaseModel):
    """Breakdown of records or jobs by lifecycle state."""
    status: str = Field(..., description="Lifecycle status string")
    count: int = Field(..., description="Record count in this status")


class RecentJobSummary(BaseModel):
    """Summary of a recently executed ingestion batch job."""
    id: str
    source_system: str
    source_format: str
    status: str
    total_records: int
    successful_records: int
    rejected_records: int
    created_at: datetime
    duration_seconds: Optional[float] = None


class RecentPatientSummary(BaseModel):
    """Summary of a recently ingested or updated patient entity."""
    id: str
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: Optional[str] = None
    gender: str
    source_system: str
    reconciliation_status: str
    created_at: datetime


class DashboardStatsResponse(BaseModel):
    """Aggregated backend statistics powering the clinical operations dashboard."""
    total_patients: int = Field(..., description="Total canonical reconciled patients")
    total_records: int = Field(..., description="Total canonical clinical records")
    total_fhir_bundles: int = Field(..., description="Total persisted HL7 FHIR R4 Bundles")
    total_fhir_resources: int = Field(..., description="Total normalized FHIR resources across all bundles")
    total_diagnostic_reports: int = Field(..., description="Total diagnostic reports")
    total_clinical_summaries: int = Field(..., description="Total AI-generated clinical summaries")
    total_jobs: int = Field(..., description="Total ingestion jobs")
    active_vectors: int = Field(..., description="Active embeddings stored in ChromaDB")
    jobs_by_status: List[StatusBreakdown] = Field(..., description="Job count by processing state")
    records_by_status: List[StatusBreakdown] = Field(..., description="Clinical records by status")
    domain_distribution: List[DomainDistribution] = Field(..., description="Domain breakdown")
    recent_jobs: List[RecentJobSummary] = Field(..., description="Latest ingestion jobs")
    recent_patients: List[RecentPatientSummary] = Field(..., description="Latest patients")
    system_status: str = Field(..., description="Overall health of backend and vector storage")
    timestamp: datetime = Field(..., description="Timestamp of stats computation")
