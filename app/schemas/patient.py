"""Pydantic schemas for patient management, demographic queries, and clinical profiles."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PatientIdentifierItem(BaseModel):
    """External identifier mapped to a patient."""
    identifier_type: str = Field(..., description="Type of identifier (MRN, SSN, SOURCE_ID)")
    value: str = Field(..., description="Identifier token/value")
    issuing_authority: str = Field(..., description="Issuing system or facility authority")


class PatientListItem(BaseModel):
    """Lightweight patient profile for directory and search tables."""
    id: str
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: Optional[str] = None
    gender: str
    source_system: str
    reconciliation_status: str
    confidence_score: float
    record_count: int = 0
    bundle_count: int = 0
    has_summary: bool = False
    created_at: datetime


class PatientPaginationResponse(BaseModel):
    """Paginated list of patients."""
    items: List[PatientListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class PatientDomainCounts(BaseModel):
    """Counts of records per clinical domain for a specific patient."""
    observations: int = 0
    conditions: int = 0
    diagnostic_reports: int = 0
    encounters: int = 0
    medications: int = 0
    procedures: int = 0
    document_references: int = 0
    total_clinical_records: int = 0


class PatientDetailResponse(BaseModel):
    """Comprehensive patient record with longitudinal counts and summary metadata."""
    id: str
    mrn: str
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    date_of_birth: Optional[str] = None
    gender: str
    source_system: str
    source_patient_id: Optional[str] = None
    reconciliation_status: str
    confidence_score: float
    contact_info: Optional[Dict[str, Any]] = None
    identifiers: List[PatientIdentifierItem] = []
    domain_counts: PatientDomainCounts
    latest_bundle_id: Optional[str] = None
    latest_bundle_version: Optional[int] = None
    has_clinical_summary: bool = False
    latest_summary_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LinkedFHIRResourceItem(BaseModel):
    """Individual clinical resource linked to a patient from the normalized FHIR graph."""
    resource_type: str
    id: str
    title: str
    date: Optional[str] = None
    status: Optional[str] = None
    details: Dict[str, Any]
    raw_resource: Dict[str, Any]
