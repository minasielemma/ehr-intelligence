"""SQLAlchemy ORM models for the EHR Ingestion, Identity, and Audit subsystem."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


def generate_uuid() -> str:
    """Generate a string representation of a random UUID4."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class IngestionJobModel(Base):
    """Represents an ingestion batch or upload job and tracks lifecycle state and metrics."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    source_format: Mapped[str] = mapped_column(String(32), nullable=False)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED", index=True)
    
    total_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflict_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    records: Mapped[List["ClinicalRecordModel"]] = relationship(
        "ClinicalRecordModel", back_populates="job", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List["AuditLogModel"]] = relationship(
        "AuditLogModel", back_populates="job", cascade="all, delete-orphan"
    )
    package_files: Mapped[List["PackageFileModel"]] = relationship(
        "PackageFileModel", back_populates="job", cascade="all, delete-orphan"
    )


class PatientModel(Base):
    """Canonical patient demographic entity representing reconciled identities."""

    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_patient_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    mrn: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    original_mrn: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    middle_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    
    date_of_birth: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    original_date_of_birth: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    administrative_gender: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    original_gender: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    contact_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW_PATIENT", index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    identifiers: Mapped[List["PatientIdentifierModel"]] = relationship(
        "PatientIdentifierModel", back_populates="patient", cascade="all, delete-orphan"
    )
    records: Mapped[List["ClinicalRecordModel"]] = relationship(
        "ClinicalRecordModel", back_populates="patient"
    )

    __table_args__ = (
        Index("ix_patient_source_mrn", "source_system", "mrn"),
        Index("ix_patient_lower_source_mrn", func.lower(source_system), "mrn"),
        Index("ix_patient_name_dob", "last_name", "first_name", "date_of_birth"),
        Index("ix_patient_lower_name_dob", func.lower(last_name), func.lower(first_name), "date_of_birth"),
    )


class PatientIdentifierModel(Base):
    """Explicit mapping of issuing authorities and external identifiers to canonical patients."""

    __tablename__ = "patient_identifiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier_type: Mapped[str] = mapped_column(String(64), nullable=False)  # MRN, SOURCE_ID, SSN
    value: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    issuing_authority: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel", back_populates="identifiers")

    __table_args__ = (
        UniqueConstraint("issuing_authority", "value", "identifier_type", name="uq_authority_identifier"),
    )


class ClinicalRecordModel(Base):
    """Canonical clinical record and intermediate representation ready for downstream FHIR mapping."""

    __tablename__ = "clinical_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, default="clinical_note", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    
    source_record_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    record_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_record_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    cleaned_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    parsed_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    job: Mapped["IngestionJobModel"] = relationship("IngestionJobModel", back_populates="records")
    patient: Mapped[Optional["PatientModel"]] = relationship("PatientModel", back_populates="records")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel", back_populates="clinical_records")

    __table_args__ = (
        Index("ix_record_job_status", "job_id", "status"),
        Index("ix_record_fingerprint", "fingerprint"),
        Index("ix_record_encounter", "encounter_id"),
    )


class AuditLogModel(Base):
    """Immutable, append-only audit trail logging per-field and per-record normalization operations."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    
    field_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    transformation_applied: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="SUCCESS")
    
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)

    job: Mapped["IngestionJobModel"] = relationship("IngestionJobModel", back_populates="audit_logs")


class OrganizationModel(Base):
    """Healthcare facility, department, or administrative organization."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    address: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    encounters: Mapped[List["EncounterModel"]] = relationship("EncounterModel", back_populates="organization")

    __table_args__ = (
        Index("ix_org_source_id", "source_system", "source_id"),
    )


class PractitionerModel(Base):
    """Healthcare practitioner, physician, or provider."""

    __tablename__ = "practitioners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    npi: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    specialty: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    encounters: Mapped[List["EncounterModel"]] = relationship("EncounterModel", back_populates="practitioner")
    medication_requests: Mapped[List["MedicationRequestModel"]] = relationship("MedicationRequestModel", back_populates="practitioner")

    __table_args__ = (
        Index("ix_practitioner_source_id", "source_system", "source_id"),
    )


class EncounterModel(Base):
    """Longitudinal clinical encounter (inpatient, outpatient, emergency, wellness)."""

    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("practitioners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    encounter_class: Mapped[str] = mapped_column(String(32), nullable=False, default="outpatient", index=True)
    encounter_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="finished", index=True)
    start_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    end_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason_display: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    service_provider: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    practitioner: Mapped[Optional["PractitionerModel"]] = relationship("PractitionerModel", back_populates="encounters")
    organization: Mapped[Optional["OrganizationModel"]] = relationship("OrganizationModel", back_populates="encounters")
    
    conditions: Mapped[List["ConditionModel"]] = relationship("ConditionModel", back_populates="encounter", cascade="all, delete-orphan")
    observations: Mapped[List["ObservationModel"]] = relationship("ObservationModel", back_populates="encounter", cascade="all, delete-orphan")
    medication_requests: Mapped[List["MedicationRequestModel"]] = relationship("MedicationRequestModel", back_populates="encounter", cascade="all, delete-orphan")
    procedures: Mapped[List["ProcedureModel"]] = relationship("ProcedureModel", back_populates="encounter", cascade="all, delete-orphan")
    claims: Mapped[List["ClaimModel"]] = relationship("ClaimModel", back_populates="encounter")
    clinical_records: Mapped[List["ClinicalRecordModel"]] = relationship("ClinicalRecordModel", back_populates="encounter")

    __table_args__ = (
        Index("ix_encounter_source_patient", "source_system", "source_id", "patient_id"),
    )


class ConditionModel(Base):
    """Diagnoses, health problems, and clinical conditions."""

    __tablename__ = "conditions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_system: Mapped[str] = mapped_column(String(128), nullable=False, default="http://hl7.org/fhir/sid/icd-10-cm")
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    clinical_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="confirmed")
    severity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    onset_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    recorded_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel", back_populates="conditions")

    __table_args__ = (
        Index("ix_condition_patient_code", "patient_id", "code"),
    )


class ObservationModel(Base):
    """Clinical observations, vital signs, laboratory tests, and exam findings."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="vital-signs", index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_system: Mapped[str] = mapped_column(String(128), nullable=False, default="http://loinc.org")
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    value_numeric: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_string: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference_range_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reference_range_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    interpretation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="final", index=True)
    effective_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel", back_populates="observations")

    __table_args__ = (
        Index("ix_observation_patient_code", "patient_id", "code"),
        Index("ix_observation_category_patient", "category", "patient_id"),
    )


class MedicationRequestModel(Base):
    """Prescriptions and medication orders."""

    __tablename__ = "medication_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    practitioner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("practitioners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_system: Mapped[str] = mapped_column(String(128), nullable=False, default="http://www.nlm.nih.gov/research/umls/rxnorm")
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    intent: Mapped[str] = mapped_column(String(32), nullable=False, default="order")
    dosage_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dose_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dose_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    authored_on: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel", back_populates="medication_requests")
    practitioner: Mapped[Optional["PractitionerModel"]] = relationship("PractitionerModel", back_populates="medication_requests")
    administrations: Mapped[List["MedicationAdministrationModel"]] = relationship("MedicationAdministrationModel", back_populates="medication_request")

    __table_args__ = (
        Index("ix_med_request_patient_code", "patient_id", "code"),
    )


class MedicationAdministrationModel(Base):
    """Documented administration of a medication to a patient."""

    __tablename__ = "medication_administrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    medication_request_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("medication_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    dosage_administered: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    medication_request: Mapped[Optional["MedicationRequestModel"]] = relationship("MedicationRequestModel", back_populates="administrations")


class ProcedureModel(Base):
    """Clinical actions, surgeries, therapies, and diagnostic procedures."""

    __tablename__ = "procedures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_system: Mapped[str] = mapped_column(String(128), nullable=False, default="http://snomed.info/sct")
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    performed_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel", back_populates="procedures")


class AllergyIntoleranceModel(Base):
    """Allergies, adverse reactions, and intolerances."""

    __tablename__ = "allergy_intolerances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clinical_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="confirmed")
    allergy_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    criticality: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")


class ImmunizationModel(Base):
    """Vaccines and immunizations administered."""

    __tablename__ = "immunizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    vaccine_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vaccine_display: Mapped[str] = mapped_column(String(255), nullable=False)
    occurrence_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    primary_source: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lot_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")


class CoverageModel(Base):
    """Insurance coverage, payers, and health plans."""

    __tablename__ = "coverages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscriber_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    coverage_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship_to_subscriber: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default="self")
    period_start: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    period_end: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    claims: Mapped[List["ClaimModel"]] = relationship("ClaimModel", back_populates="coverage")


class ClaimModel(Base):
    """Healthcare billing claims, charges, and insurance adjudications."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    coverage_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("coverages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False, default="institutional", index=True)
    use: Mapped[str] = mapped_column(String(32), nullable=False, default="claim")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="USD")
    created_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel", back_populates="claims")
    coverage: Mapped[Optional["CoverageModel"]] = relationship("CoverageModel", back_populates="claims")


class CarePlanModel(Base):
    """Longitudinal care plans and treatment goals."""

    __tablename__ = "care_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    intent: Mapped[str] = mapped_column(String(32), nullable=False, default="plan")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    period_start: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    period_end: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")


class ConsentModel(Base):
    """Patient consent directives and authorizations."""

    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="treatment")
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    date_time: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")


class ServiceRequestModel(Base):
    """Clinical orders, referrals, and lab/imaging service requests."""

    __tablename__ = "service_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    intent: Mapped[str] = mapped_column(String(32), nullable=False, default="order")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    authored_on: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel")


class DiagnosticReportModel(Base):
    """Diagnostic reports, laboratory panels, and pathology summaries."""

    __tablename__ = "diagnostic_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    service_request_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("service_requests.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="final", index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="LAB")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    conclusion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel")


class ImagingStudyModel(Base):
    """Radiology and imaging studies (X-ray, CT, MRI, Ultrasound)."""

    __tablename__ = "imaging_studies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    modality: Mapped[str] = mapped_column(String(32), nullable=False, default="CT", index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    number_of_series: Mapped[Optional[int]] = mapped_column(Integer, default=1)
    number_of_instances: Mapped[Optional[int]] = mapped_column(Integer, default=1)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel")


class DocumentReferenceModel(Base):
    """Clinical document references, discharge summaries, and notes."""

    __tablename__ = "document_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("encounters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="current", index=True)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, default="clinical_note")
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped["PatientModel"] = relationship("PatientModel")
    encounter: Mapped[Optional["EncounterModel"]] = relationship("EncounterModel")


class ProvenanceModel(Base):
    """HL7 FHIR Provenance tracking authoring, source entity, and activity history."""

    __tablename__ = "provenances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    patient_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_resource_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    activity: Mapped[str] = mapped_column(String(64), nullable=False, default="CREATE")
    agent_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    agent_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    patient: Mapped[Optional["PatientModel"]] = relationship("PatientModel")


class PackageFileModel(Base):
    """Tracks per-file and per-domain execution status within multi-file EHR export packages."""

    __tablename__ = "package_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    total_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped["IngestionJobModel"] = relationship("IngestionJobModel", back_populates="package_files")


class FHIRBundleModel(Base):
    """Persisted HL7 FHIR R4 Bundles representing patient-centric clinical records."""

    __tablename__ = "fhir_bundles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    bundle_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_mrn: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    bundle_type: Mapped[str] = mapped_column(String(32), nullable=False, default="collection", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="VALID", index=True)
    resource_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bundle_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_report_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    patient: Mapped["PatientModel"] = relationship("PatientModel")

    __table_args__ = (
        Index("ix_fhir_bundle_patient_version", "patient_id", "version", unique=True),
    )
