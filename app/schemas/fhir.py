"""Pydantic v2 schemas for HL7 FHIR R4 Normalization, Validation, and Storage."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.canonical import CanonicalClinicalRecord, CanonicalPatient


class ValidationSeverity(str, Enum):
    """Severity classification for FHIR conformance issues."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFORMATION = "INFORMATION"


class ValidationStatus(str, Enum):
    """Overall status of FHIR validation."""
    VALID = "VALID"
    INVALID = "INVALID"
    WARNING = "WARNING"


class FHIRValidationIssue(BaseModel):
    """Detailed FHIR validation issue report entry."""
    model_config = ConfigDict(extra="ignore")

    resource_type: str = Field(..., description="FHIR resource type (e.g. Patient, DocumentReference)")
    resource_id: Optional[str] = Field(default=None, description="Resource identifier where issue occurred")
    severity: ValidationSeverity = Field(..., description="Severity: ERROR, WARNING, INFORMATION")
    fhir_path: str = Field(..., description="FHIR element path (e.g. Patient.birthDate, DocumentReference.subject)")
    error_code: str = Field(..., description="Machine-readable error category or code")
    description: str = Field(..., description="Human-readable description of the issue")
    recommended_action: str = Field(..., description="Actionable recommendation to remediate the defect")


class FHIRValidationReport(BaseModel):
    """Comprehensive validation report for an HL7 FHIR R4 resource or Bundle."""
    model_config = ConfigDict(extra="ignore")

    patient_identifier: str = Field(..., description="Associated patient MRN or identifier")
    bundle_id: Optional[str] = Field(default=None, description="FHIR Bundle ID if validating a bundle")
    status: ValidationStatus = Field(..., description="Overall conformance status: VALID, INVALID, WARNING")
    total_resources: int = Field(default=0, description="Total resources evaluated")
    valid_resources: int = Field(default=0, description="Count of conforming resources")
    invalid_resources: int = Field(default=0, description="Count of resources with errors")
    error_count: int = Field(default=0, description="Total count of ERROR issues")
    warning_count: int = Field(default=0, description="Total count of WARNING issues")
    info_count: int = Field(default=0, description="Total count of INFORMATION issues")
    issues: List[FHIRValidationIssue] = Field(default_factory=list, description="List of granular validation issues")
    validated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when validation was performed",
    )


class FHIRBundleSummary(BaseModel):
    """Summary of a stored FHIR R4 Bundle."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Internal database UUID")
    bundle_id: str = Field(..., description="FHIR Bundle identifier")
    patient_id: str = Field(..., description="Associated patient canonical UUID")
    patient_mrn: str = Field(..., description="Patient Medical Record Number")
    bundle_type: str = Field(..., description="Bundle type: collection, transaction, etc.")
    version: int = Field(..., description="Bundle version number")
    status: str = Field(..., description="Validation status: VALID, INVALID, WARNING")
    resource_count: int = Field(..., description="Count of resources contained in the bundle")
    content_hash: str = Field(..., description="Deterministic SHA-256 hash of bundle content")
    file_path: Optional[str] = Field(default=None, description="Filesystem path if stored on disk")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class FHIRBundlePaginationResponse(BaseModel):
    """Paginated list of stored FHIR Bundle summaries."""
    model_config = ConfigDict(extra="ignore")

    items: List[FHIRBundleSummary] = Field(..., description="List of bundle summaries")
    total: int = Field(..., description="Total count of bundles matching query criteria")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Page size limit")
    total_pages: int = Field(..., description="Total available pages")


class FHIRNormalizationRequest(BaseModel):
    """Request payload for direct FHIR R4 normalization of cleaned clinical data."""
    model_config = ConfigDict(extra="ignore")

    patient: Optional[CanonicalPatient] = Field(default=None, description="Cleaned canonical patient representation")
    records: Optional[List[CanonicalClinicalRecord]] = Field(default=None, description="Cleaned clinical records")
    patient_id: Optional[str] = Field(default=None, description="Existing database patient UUID to normalize")
    bundle_type: str = Field(default="collection", description="Target Bundle type: collection or transaction")
    save_to_store: bool = Field(default=True, description="Persist validated bundle to SQLite and disk storage")


class FHIRNormalizationResponse(BaseModel):
    """Response payload returned after FHIR R4 normalization and validation."""
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(..., description="True if normalization and validation succeeded without fatal errors")
    bundle_id: Optional[str] = Field(default=None, description="Generated FHIR Bundle ID")
    patient_id: Optional[str] = Field(default=None, description="Referenced patient ID")
    patient_mrn: Optional[str] = Field(default=None, description="Referenced patient MRN")
    version: int = Field(default=1, description="Version number of stored bundle")
    bundle: Optional[Dict[str, Any]] = Field(default=None, description="Full FHIR R4 Bundle JSON if generated")
    validation_report: FHIRValidationReport = Field(..., description="Detailed validation report")
    storage_path: Optional[str] = Field(default=None, description="Filesystem path if saved to local disk")
    persisted: bool = Field(default=False, description="True if persisted to the validated output store")


class FHIRValidationRequest(BaseModel):
    """Request payload for validating an arbitrary FHIR R4 resource or Bundle."""
    model_config = ConfigDict(extra="ignore")

    resource: Dict[str, Any] = Field(..., description="FHIR resource or Bundle JSON to validate")
    patient_identifier: Optional[str] = Field(default=None, description="Optional patient identifier for reference integrity")
