"""Canonical intermediate representations (Pydantic v2) for EHR Ingestion and FHIR R4 mapping."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ReconciliationStatus(str, Enum):
    """Explicit patient identity reconciliation statuses."""
    MATCHED = "MATCHED"
    NEW_PATIENT = "NEW_PATIENT"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class JobStatus(str, Enum):
    """Ingestion job processing lifecycle states."""
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


class RecordStatus(str, Enum):
    """Per-record processing and validation states."""
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    NORMALIZED = "NORMALIZED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    FAILED = "FAILED"


class AuditOutcome(str, Enum):
    """Audit transformation outcomes."""
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILURE = "FAILURE"
    ESCALATED = "ESCALATED"


class MappingProfile(BaseModel):
    """Configurable source-specific mapping profile for heterogeneous EHR data sources."""
    model_config = ConfigDict(extra="ignore")

    source_system: str = Field(default="generic_ehr", description="Identifier of the source clinical system")
    mrn_field: str = Field(default="mrn", description="Path/key to patient MRN")
    patient_id_field: Optional[str] = Field(default="patient_id", description="Source internal patient ID")
    first_name_field: str = Field(default="first_name", description="Path/key to patient first name")
    middle_name_field: Optional[str] = Field(default="middle_name", description="Path/key to patient middle name")
    last_name_field: str = Field(default="last_name", description="Path/key to patient last name")
    dob_field: str = Field(default="dob", description="Path/key to date of birth")
    gender_field: str = Field(default="gender", description="Path/key to administrative gender")
    record_date_field: Optional[str] = Field(default="record_date", description="Path/key to encounter/record date")
    record_type_field: Optional[str] = Field(default="record_type", description="Path/key to document or clinical type")
    content_field: Optional[str] = Field(default="clinical_text", description="Path/key to clinical text or notes")
    date_format_hint: Optional[str] = Field(default=None, description="Expected date format hint (e.g. 'YYYY-MM-DD', 'DD/MM/YYYY')")
    csv_delimiter: Optional[str] = Field(default=None, description="Explicit CSV delimiter override")
    domain: Optional[str] = Field(default=None, description="Explicit healthcare domain override (e.g. 'provenances', 'encounters', 'observations')")


class RawRecord(BaseModel):
    """Standardized raw record emitted by multi-format parsers before normalization."""
    model_config = ConfigDict(extra="allow")

    source_record_id: Optional[str] = None
    source_system: str = "unknown"
    source_format: str = "json"
    raw_patient: Dict[str, Any] = Field(default_factory=dict)
    raw_document: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    line_number: Optional[int] = None


class CanonicalPatient(BaseModel):
    """Canonical patient representation ready for HL7 FHIR R4 Patient resource generation."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Canonical internal UUID for the reconciled patient")
    source_system: str = Field(..., description="Originating hospital or source EHR system")
    source_patient_id: Optional[str] = Field(default=None, description="Source system specific patient key")
    mrn: str = Field(..., description="Normalized Medical Record Number scoped to issuing system")
    original_mrn: Optional[str] = Field(default=None, description="Preserved raw unnormalized MRN")
    first_name: str = Field(..., description="Cleaned first/given name")
    middle_name: Optional[str] = Field(default=None, description="Cleaned middle name")
    last_name: str = Field(..., description="Cleaned family/last name")
    date_of_birth: Optional[str] = Field(default=None, description="Normalized ISO 8601 date (YYYY-MM-DD)")
    original_date_of_birth: Optional[str] = Field(default=None, description="Preserved raw date of birth string")
    administrative_gender: str = Field(default="unknown", description="Canonical administrative gender: male, female, other, unknown")
    original_gender: Optional[str] = Field(default=None, description="Preserved raw gender input")
    contact_info: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Structured phone, email, address")
    reconciliation_status: ReconciliationStatus = Field(default=ReconciliationStatus.NEW_PATIENT)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Audit tracking and origin metadata")


class CanonicalClinicalRecord(BaseModel):
    """Canonical intermediate representation of an EHR document/observation ready for FHIR mapping."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Canonical internal record UUID")
    job_id: str = Field(..., description="Associated ingestion job UUID")
    patient_id: Optional[str] = Field(default=None, description="Referenced canonical patient UUID")
    patient: Optional[CanonicalPatient] = Field(default=None, description="Associated patient entity")
    record_type: str = Field(default="clinical_note", description="Clinical type: progress_note, lab_result, imaging, etc.")
    status: RecordStatus = Field(default=RecordStatus.PENDING)
    fingerprint: str = Field(..., description="SHA-256 deterministic record fingerprint")
    source_record_id: Optional[str] = Field(default=None, description="Originating record identifier")
    record_date: Optional[str] = Field(default=None, description="Normalized ISO 8601 record timestamp")
    original_record_date: Optional[str] = Field(default=None, description="Preserved raw record date")
    cleaned_text: Optional[str] = Field(default=None, description="Sanitized, clinically preserved narrative text")
    original_content: Optional[str] = Field(default=None, description="Immutable raw document content")
    parsed_payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Structured observations, labs, or details")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Source provenance and parsing details")
    validation_errors: List[Dict[str, Any]] = Field(default_factory=list, description="Validation issues detected")


class IngestionMetadata(BaseModel):
    """Metadata tracking the execution of an ingestion job."""
    model_config = ConfigDict(extra="ignore")

    job_id: str
    source_format: str
    source_system: str
    upload_timestamp: datetime
    processing_timestamp: Optional[datetime] = None
    status: JobStatus = JobStatus.RECEIVED
    error_info: Optional[str] = None


class AuditRecord(BaseModel):
    """Per-field and per-record audit transformation log."""
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    job_id: str
    record_id: Optional[str] = None
    field_name: Optional[str] = None
    original_value: Optional[str] = None
    normalized_value: Optional[str] = None
    transformation_applied: str
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    processing_component: str
    outcome: AuditOutcome = AuditOutcome.SUCCESS
