"""Unit tests for patient identity reconciliation and conflict detection."""

import pytest
from app.ingestion.reconciliation.patient_matcher import (
    PatientIdentityReconciler,
    ReconciliationDecision,
)
from app.models.ingestion import PatientModel
from app.schemas.canonical import CanonicalPatient, ReconciliationStatus


def test_reconciliation_exact_match() -> None:
    """Verify exact match within same source system and consistent demographics."""
    candidate = CanonicalPatient(
        id="cand-1",
        source_system="hospital_a",
        mrn="MRN-100",
        first_name="Eleanor",
        last_name="Roosevelt",
        date_of_birth="1984-10-11",
        administrative_gender="female",
    )
    existing = [
        PatientModel(
            id="exist-1",
            source_system="hospital_a",
            mrn="MRN-100",
            first_name="Eleanor",
            last_name="Roosevelt",
            date_of_birth="1984-10-11",
            administrative_gender="female",
        )
    ]

    decision = PatientIdentityReconciler.reconcile(
        candidate=candidate,
        existing_patients_by_mrn=existing,
        existing_patients_by_demographics=existing,
        job_id="job-1",
    )
    assert decision.status == ReconciliationStatus.MATCHED
    assert decision.canonical_patient_id == "exist-1"
    assert decision.confidence_score == 1.0


def test_reconciliation_identity_conflict() -> None:
    """Verify identity conflict when same MRN in same system has conflicting demographics."""
    candidate = CanonicalPatient(
        id="cand-2",
        source_system="hospital_a",
        mrn="MRN-100",
        first_name="Winston",
        last_name="Churchill",
        date_of_birth="1974-11-30",
        administrative_gender="male",
    )
    existing = [
        PatientModel(
            id="exist-1",
            source_system="hospital_a",
            mrn="MRN-100",
            first_name="Eleanor",
            last_name="Roosevelt",
            date_of_birth="1984-10-11",
            administrative_gender="female",
        )
    ]

    decision = PatientIdentityReconciler.reconcile(
        candidate=candidate,
        existing_patients_by_mrn=existing,
        existing_patients_by_demographics=[],
        job_id="job-1",
    )
    assert decision.status == ReconciliationStatus.IDENTITY_CONFLICT
    assert decision.confidence_score == 0.0
    assert "IDENTITY CONFLICT" in decision.conflict_details


def test_reconciliation_possible_duplicate() -> None:
    """Verify matching name and DOB across different MRNs flags as POSSIBLE_DUPLICATE."""
    candidate = CanonicalPatient(
        id="cand-3",
        source_system="hospital_b",
        mrn="MRN-999",
        first_name="Eleanor",
        last_name="Roosevelt",
        date_of_birth="1984-10-11",
        administrative_gender="female",
    )
    existing_by_demo = [
        PatientModel(
            id="exist-1",
            source_system="hospital_a",
            mrn="MRN-100",
            first_name="Eleanor",
            last_name="Roosevelt",
            date_of_birth="1984-10-11",
            administrative_gender="female",
        )
    ]

    decision = PatientIdentityReconciler.reconcile(
        candidate=candidate,
        existing_patients_by_mrn=[],
        existing_patients_by_demographics=existing_by_demo,
        job_id="job-1",
    )
    assert decision.status == ReconciliationStatus.POSSIBLE_DUPLICATE
    assert "POSSIBLE DUPLICATE" in decision.conflict_details


def test_reconciliation_missing_dob_escalation() -> None:
    """Verify patient missing DOB is escalated for manual demographic review."""
    candidate = CanonicalPatient(
        id="cand-4",
        source_system="hospital_c",
        mrn="MRN-777",
        first_name="George",
        last_name="Patton",
        date_of_birth=None,
        administrative_gender="male",
    )

    decision = PatientIdentityReconciler.reconcile(
        candidate=candidate,
        existing_patients_by_mrn=[],
        existing_patients_by_demographics=[],
        job_id="job-1",
    )
    assert decision.status == ReconciliationStatus.MANUAL_REVIEW_REQUIRED


def test_reconciliation_new_patient() -> None:
    """Verify completely unique patient is registered as NEW_PATIENT."""
    candidate = CanonicalPatient(
        id="cand-5",
        source_system="hospital_c",
        mrn="MRN-555",
        first_name="Benjamin",
        last_name="Franklin",
        date_of_birth="1990-01-17",
        administrative_gender="male",
    )

    decision = PatientIdentityReconciler.reconcile(
        candidate=candidate,
        existing_patients_by_mrn=[],
        existing_patients_by_demographics=[],
        job_id="job-1",
    )
    assert decision.status == ReconciliationStatus.NEW_PATIENT
    assert decision.confidence_score == 1.0
