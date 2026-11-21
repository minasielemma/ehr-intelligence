"""Deterministic patient identity reconciliation and conflict detection engine.

Safeguards against cross-patient record contamination by strictly evaluating identifier
matching, authority boundaries, and demographic consistency.
"""

from typing import List, Optional, Tuple
import uuid

from app.models.ingestion import PatientModel
from app.schemas.canonical import (
    AuditOutcome,
    AuditRecord,
    CanonicalPatient,
    ReconciliationStatus,
)


class ReconciliationDecision:
    """Outcome of patient identity reconciliation."""

    def __init__(
        self,
        status: ReconciliationStatus,
        canonical_patient_id: str,
        matched_patient: Optional[PatientModel] = None,
        confidence_score: float = 1.0,
        conflict_details: Optional[str] = None,
        audit_events: Optional[List[AuditRecord]] = None,
    ) -> None:
        self.status = status
        self.canonical_patient_id = canonical_patient_id
        self.matched_patient = matched_patient
        self.confidence_score = confidence_score
        self.conflict_details = conflict_details
        self.audit_events = audit_events or []


class PatientIdentityReconciler:
    """Deterministic patient identity matcher and conflict detection service."""

    @classmethod
    def reconcile(
        cls,
        candidate: CanonicalPatient,
        existing_patients_by_mrn: List[PatientModel],
        existing_patients_by_demographics: List[PatientModel],
        job_id: str,
    ) -> ReconciliationDecision:
        """Evaluate candidate patient against existing database records deterministically.
        
        Evaluates exact MRN matches, demographic consistency, cross-system overlaps,
        and identifier conflicts.
        """
        audit_events: List[AuditRecord] = []

        system_mrn_matches = [
            p for p in existing_patients_by_mrn
            if p.source_system.lower() == candidate.source_system.lower()
            and p.mrn == candidate.mrn
        ]

        if system_mrn_matches:
            matched_p = system_mrn_matches[0]

            name_matches = (
                matched_p.last_name.lower() == candidate.last_name.lower()
                and (
                    matched_p.first_name.lower() == candidate.first_name.lower()
                    or candidate.first_name.lower().startswith(matched_p.first_name.lower()[:3])
                )
            )
            dob_matches = (
                matched_p.date_of_birth is None
                or candidate.date_of_birth is None
                or matched_p.date_of_birth == candidate.date_of_birth
            )

            is_placeholder = (
                matched_p.first_name == "UNRESOLVED"
                and matched_p.last_name == "PATIENT"
                and matched_p.reconciliation_status == ReconciliationStatus.MANUAL_REVIEW_REQUIRED.value
            )

            if is_placeholder or (name_matches and dob_matches):
                match_reason = (
                    f"Reconciled and populated previous placeholder patient in {candidate.source_system}"
                    if is_placeholder
                    else f"Matched existing patient identity in {candidate.source_system}"
                )
                audit_events.append(
                    AuditRecord(
                        audit_id=str(uuid.uuid4()),
                        job_id=job_id,
                        record_id=candidate.id,
                        field_name="mrn",
                        original_value=candidate.mrn,
                        normalized_value=matched_p.id,
                        transformation_applied="PATIENT_IDENTITY_EXACT_MATCH",
                        reason=match_reason,
                        processing_component="PatientIdentityReconciler",
                        outcome=AuditOutcome.SUCCESS,
                    )
                )
                return ReconciliationDecision(
                    status=ReconciliationStatus.MATCHED,
                    canonical_patient_id=matched_p.id,
                    matched_patient=matched_p,
                    confidence_score=1.0,
                    audit_events=audit_events,
                )
            else:
                conflict_msg = (
                    f"IDENTITY CONFLICT: MRN '{candidate.mrn}' in system '{candidate.source_system}' "
                    f"matches existing patient '{matched_p.id}' ({matched_p.last_name}, {matched_p.first_name}, DOB:{matched_p.date_of_birth}) "
                    f"but incoming demographics differ ({candidate.last_name}, {candidate.first_name}, DOB:{candidate.date_of_birth})."
                )
                audit_events.append(
                    AuditRecord(
                        audit_id=str(uuid.uuid4()),
                        job_id=job_id,
                        record_id=candidate.id,
                        field_name="mrn",
                        original_value=candidate.mrn,
                        normalized_value=None,
                        transformation_applied="PATIENT_IDENTITY_CONFLICT_DETECTED",
                        reason=conflict_msg,
                        processing_component="PatientIdentityReconciler",
                        outcome=AuditOutcome.ESCALATED,
                    )
                )
                return ReconciliationDecision(
                    status=ReconciliationStatus.IDENTITY_CONFLICT,
                    canonical_patient_id=candidate.id,
                    confidence_score=0.0,
                    conflict_details=conflict_msg,
                    audit_events=audit_events,
                )

        if candidate.date_of_birth and existing_patients_by_demographics:
            for demo_p in existing_patients_by_demographics:
                if (
                    demo_p.last_name.lower() == candidate.last_name.lower()
                    and demo_p.first_name.lower() == candidate.first_name.lower()
                    and demo_p.date_of_birth == candidate.date_of_birth
                ):
                    warning_msg = (
                        f"POSSIBLE DUPLICATE: Incoming patient matches name and DOB with "
                        f"existing patient '{demo_p.id}' (Source: {demo_p.source_system}, MRN: {demo_p.mrn}) "
                        f"but has distinct MRN '{candidate.mrn}'. Escalated for manual review."
                    )
                    audit_events.append(
                        AuditRecord(
                            audit_id=str(uuid.uuid4()),
                            job_id=job_id,
                            record_id=candidate.id,
                            field_name="patient_identity",
                            original_value=candidate.mrn,
                            normalized_value=demo_p.id,
                            transformation_applied="POSSIBLE_DUPLICATE_FLAGGED",
                            reason=warning_msg,
                            processing_component="PatientIdentityReconciler",
                            outcome=AuditOutcome.WARNING,
                        )
                    )
                    return ReconciliationDecision(
                        status=ReconciliationStatus.POSSIBLE_DUPLICATE,
                        canonical_patient_id=candidate.id,
                        matched_patient=demo_p,
                        confidence_score=0.75,
                        conflict_details=warning_msg,
                        audit_events=audit_events,
                    )

        if not candidate.date_of_birth:
            warning_msg = "Patient missing date of birth; flagged for manual demographic review."
            audit_events.append(
                AuditRecord(
                    audit_id=str(uuid.uuid4()),
                    job_id=job_id,
                    record_id=candidate.id,
                    field_name="date_of_birth",
                    original_value=None,
                    normalized_value=None,
                    transformation_applied="MANUAL_REVIEW_MISSING_DOB",
                    reason=warning_msg,
                    processing_component="PatientIdentityReconciler",
                    outcome=AuditOutcome.WARNING,
                )
            )
            return ReconciliationDecision(
                status=ReconciliationStatus.MANUAL_REVIEW_REQUIRED,
                canonical_patient_id=candidate.id,
                confidence_score=0.6,
                conflict_details=warning_msg,
                audit_events=audit_events,
            )

        audit_events.append(
            AuditRecord(
                audit_id=str(uuid.uuid4()),
                job_id=job_id,
                record_id=candidate.id,
                field_name="patient_identity",
                original_value=candidate.mrn,
                normalized_value=candidate.id,
                transformation_applied="NEW_PATIENT_REGISTERED",
                reason=f"New unique patient registered in {candidate.source_system}",
                processing_component="PatientIdentityReconciler",
                outcome=AuditOutcome.SUCCESS,
            )
        )
        return ReconciliationDecision(
            status=ReconciliationStatus.NEW_PATIENT,
            canonical_patient_id=candidate.id,
            confidence_score=1.0,
            audit_events=audit_events,
        )
