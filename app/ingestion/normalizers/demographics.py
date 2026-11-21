"""Comprehensive demographic normalization service for patient identities."""

import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.ingestion.normalizers.date_normalizer import DateNormalizer
from app.ingestion.normalizers.gender_normalizer import GenderNormalizer
from app.ingestion.normalizers.mrn_normalizer import MRNNormalizer
from app.schemas.canonical import (
    AuditOutcome,
    AuditRecord,
    CanonicalPatient,
    MappingProfile,
    ReconciliationStatus,
)


class DemographicNormalizer:
    """Orchestrates normalization for patient demographics and creates audit entries."""

    NAME_WHITESPACE_REGEX = re.compile(r"\s+")

    @classmethod
    def clean_name_part(cls, val: Optional[str]) -> Tuple[Optional[str], bool]:
        """Trim whitespace and collapse multiple internal spaces in name tokens."""
        if not val or not str(val).strip():
            return None, False
        original = str(val)
        cleaned = cls.NAME_WHITESPACE_REGEX.sub(" ", original.strip()).strip()
        return cleaned, cleaned != original

    @classmethod
    def normalize_patient(
        cls,
        raw_data: Dict[str, Any],
        source_system: str,
        job_id: str,
        mapping: Optional[MappingProfile] = None,
    ) -> Tuple[Optional[CanonicalPatient], List[AuditRecord], List[Dict[str, Any]]]:
        """Normalize patient demographics from raw dictionary using configurable field mappings.
        
        Returns:
            Tuple of (CanonicalPatient, list of AuditRecords, list of validation issues)
        """
        mp = mapping or MappingProfile(source_system=source_system)
        audit_events: List[AuditRecord] = []
        validation_issues: List[Dict[str, Any]] = []

        raw_mrn = raw_data.get(mp.mrn_field)
        if raw_mrn is None:
            for alt in ["medical_record_number", "patient_mrn", "MRN", "id"]:
                if alt in raw_data and raw_data[alt]:
                    raw_mrn = raw_data[alt]
                    break

        norm_mrn, orig_mrn, mrn_tx = MRNNormalizer.normalize_mrn(raw_mrn, source_system=source_system)
        if not norm_mrn:
            validation_issues.append({"field": "mrn", "error": "MRN is required for patient identity but was missing or empty."})
        elif mrn_tx:
            audit_events.append(
                AuditRecord(
                    audit_id=str(uuid.uuid4()),
                    job_id=job_id,
                    field_name="mrn",
                    original_value=str(orig_mrn),
                    normalized_value=norm_mrn,
                    transformation_applied=mrn_tx,
                    reason="Normalized whitespace and format in Medical Record Number",
                    processing_component="MRNNormalizer",
                    outcome=AuditOutcome.SUCCESS,
                )
            )

        raw_fname = raw_data.get(mp.first_name_field) or raw_data.get("fname") or raw_data.get("given_name")
        raw_mname = raw_data.get(mp.middle_name_field) or raw_data.get("mname") if mp.middle_name_field else None
        raw_lname = raw_data.get(mp.last_name_field) or raw_data.get("lname") or raw_data.get("family_name")

        clean_fname, fname_modified = cls.clean_name_part(raw_fname)
        clean_mname, mname_modified = cls.clean_name_part(raw_mname)
        clean_lname, lname_modified = cls.clean_name_part(raw_lname)

        if not clean_fname:
            validation_issues.append({"field": "first_name", "error": "Patient first name is missing or empty."})
        elif fname_modified:
            audit_events.append(
                AuditRecord(
                    audit_id=str(uuid.uuid4()),
                    job_id=job_id,
                    field_name="first_name",
                    original_value=str(raw_fname),
                    normalized_value=clean_fname,
                    transformation_applied="NAME_WHITESPACE_TRIMMED",
                    reason="Trimmed excessive whitespace from patient first name",
                    processing_component="DemographicNormalizer",
                    outcome=AuditOutcome.SUCCESS,
                )
            )

        if not clean_lname:
            validation_issues.append({"field": "last_name", "error": "Patient last name is missing or empty."})
        elif lname_modified:
            audit_events.append(
                AuditRecord(
                    audit_id=str(uuid.uuid4()),
                    job_id=job_id,
                    field_name="last_name",
                    original_value=str(raw_lname),
                    normalized_value=clean_lname,
                    transformation_applied="NAME_WHITESPACE_TRIMMED",
                    reason="Trimmed excessive whitespace from patient last name",
                    processing_component="DemographicNormalizer",
                    outcome=AuditOutcome.SUCCESS,
                )
            )

        raw_dob = raw_data.get(mp.dob_field) or raw_data.get("date_of_birth") or raw_data.get("birth_date")
        dob_result = DateNormalizer.normalize_date(raw_dob, format_hint=mp.date_format_hint)

        norm_dob = None
        orig_dob = dob_result.original_value or None

        if dob_result.is_ambiguous:
            validation_issues.append({
                "field": "date_of_birth",
                "error": dob_result.error_message,
                "is_ambiguous": True,
            })
            audit_events.append(
                AuditRecord(
                    audit_id=str(uuid.uuid4()),
                    job_id=job_id,
                    field_name="date_of_birth",
                    original_value=str(raw_dob),
                    normalized_value=None,
                    transformation_applied="AMBIGUOUS_DATE_FLAGGED",
                    reason=dob_result.error_message or "Ambiguous calendar date format",
                    processing_component="DateNormalizer",
                    outcome=AuditOutcome.WARNING,
                )
            )
        elif not dob_result.is_valid:
            if raw_dob:
                validation_issues.append({
                    "field": "date_of_birth",
                    "error": dob_result.error_message or f"Invalid date of birth: {raw_dob}",
                })
        else:
            norm_dob = dob_result.normalized_value
            if norm_dob != raw_dob:
                audit_events.append(
                    AuditRecord(
                        audit_id=str(uuid.uuid4()),
                        job_id=job_id,
                        field_name="date_of_birth",
                        original_value=str(raw_dob),
                        normalized_value=norm_dob,
                        transformation_applied=f"DATE_NORMALIZED_{dob_result.applied_format}",
                        reason="Normalized date of birth to standard ISO 8601 (YYYY-MM-DD)",
                        processing_component="DateNormalizer",
                        outcome=AuditOutcome.SUCCESS,
                    )
                )

        raw_gender = raw_data.get(mp.gender_field) or raw_data.get("administrative_gender") or raw_data.get("sex")
        norm_gender, orig_gender, gender_tx = GenderNormalizer.normalize_gender(raw_gender)
        if gender_tx:
            audit_events.append(
                AuditRecord(
                    audit_id=str(uuid.uuid4()),
                    job_id=job_id,
                    field_name="administrative_gender",
                    original_value=str(orig_gender),
                    normalized_value=norm_gender,
                    transformation_applied=gender_tx,
                    reason="Normalized administrative gender code to canonical FHIR vocabulary",
                    processing_component="GenderNormalizer",
                    outcome=AuditOutcome.SUCCESS,
                )
            )

        contact_info: Dict[str, Any] = {}
        for ckey in ["phone", "telephone", "phone_number", "email", "address", "city", "state", "postal_code", "zip"]:
            if ckey in raw_data and raw_data[ckey]:
                contact_info[ckey] = raw_data[ckey]

        source_patient_id = None
        if mp.patient_id_field and mp.patient_id_field in raw_data:
            source_patient_id = str(raw_data[mp.patient_id_field]).strip()

        if not norm_mrn or not clean_fname or not clean_lname:
            return None, audit_events, validation_issues

        canonical_patient = CanonicalPatient(
            id=str(uuid.uuid4()),
            source_system=source_system,
            source_patient_id=source_patient_id,
            mrn=norm_mrn,
            original_mrn=orig_mrn,
            first_name=clean_fname,
            middle_name=clean_mname,
            last_name=clean_lname,
            date_of_birth=norm_dob,
            original_date_of_birth=orig_dob,
            administrative_gender=norm_gender,
            original_gender=orig_gender,
            contact_info=contact_info,
            reconciliation_status=ReconciliationStatus.NEW_PATIENT,
            confidence_score=1.0,
            provenance={"job_id": job_id, "source_system": source_system},
        )

        return canonical_patient, audit_events, validation_issues
