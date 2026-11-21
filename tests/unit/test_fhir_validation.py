"""Unit tests for FHIR R4 Validator and Structured Validation Reporting."""

import pytest

from app.fhir.validator import FHIRValidator
from app.schemas.fhir import ValidationSeverity, ValidationStatus


def test_validator_detailed_valid_patient():
    """Verify detailed validation approves a fully conforming Patient resource with 0 issues."""
    patient = {
        "resourceType": "Patient",
        "id": "pat-valid-01",
        "active": True,
        "identifier": [
            {
                "system": "http://hospital.smarthealth.org/mrn",
                "value": "MRN-100",
                "type": {"coding": [{"code": "MR"}]},
            }
        ],
        "name": [{"family": "Smith", "given": ["Jane"]}],
        "gender": "female",
        "birthDate": "1992-06-15",
    }
    issues = FHIRValidator.validate_resource_detailed(patient)
    errors = [i for i in issues if i.severity == ValidationSeverity.ERROR]
    assert len(errors) == 0


def test_validator_detailed_invalid_birthdate_format():
    """Verify validator flags non-conformant birthDate strings as ERROR."""
    patient = {
        "resourceType": "Patient",
        "id": "pat-invalid-dob",
        "name": [{"family": "BadDate"}],
        "birthDate": "15/06/1992",  # Invalid for FHIR (must be YYYY-MM-DD)
    }
    issues = FHIRValidator.validate_resource_detailed(patient)
    err = next((i for i in issues if "birthDate" in i.fhir_path), None)
    assert err is not None
    assert err.severity == ValidationSeverity.ERROR
    assert any("YYYY-MM-DD" in i.recommended_action or "birthDate" in i.fhir_path for i in issues)


def test_validator_detailed_invalid_administrative_gender():
    """Verify validator catches illegal administrative gender values."""
    patient = {
        "resourceType": "Patient",
        "id": "pat-bad-gender",
        "name": [{"family": "User"}],
        "gender": "INVALID_GENDER",
    }
    issues = FHIRValidator.validate_resource_detailed(patient)
    err = next((i for i in issues if "gender" in i.fhir_path), None)
    assert err is not None
    assert err.severity == ValidationSeverity.ERROR
    assert "male" in err.description.lower() and "female" in err.description.lower()


def test_validator_detailed_document_reference_missing_content():
    """Verify DocumentReference without content attachment is flagged as ERROR."""
    doc = {
        "resourceType": "DocumentReference",
        "id": "doc-no-content",
        "status": "current",
        "subject": {"reference": "Patient/p1"},
        "content": [],  # Illegal: must contain at least 1 attachment
    }
    issues = FHIRValidator.validate_resource_detailed(doc)
    err = next((i for i in issues if "content" in i.fhir_path), None)
    assert err is not None
    assert err.severity == ValidationSeverity.ERROR
    assert err.error_code in ["MISSING_CONTENT", "VALUE_ERROR_LIST_MIN_ITEMS"]


def test_validator_bundle_detailed_cross_patient_leak():
    """Verify validate_bundle_detailed flags cross-patient reference leakage."""
    bundle = {
        "resourceType": "Bundle",
        "id": "b-cross",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "patient-1",
                    "name": [{"family": "One"}],
                }
            },
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-foreign",
                    "status": "current",
                    "subject": {"reference": "Patient/patient-FOREIGN"},
                    "content": [{"attachment": {"contentType": "text/plain", "data": "VGVzdA=="}}],
                }
            },
        ],
    }

    report = FHIRValidator.validate_bundle_detailed(bundle, expected_patient_id="patient-1")

    assert report.status == ValidationStatus.INVALID
    assert report.error_count >= 1

    leak_issue = next(
        (i for i in report.issues if i.error_code == "CROSS_PATIENT_REFERENCE_VIOLATION"),
        None,
    )
    assert leak_issue is not None
    assert "Patient/patient-FOREIGN" in leak_issue.description
    assert leak_issue.severity == ValidationSeverity.ERROR


def test_validator_bundle_detailed_unresolved_internal_reference_warning():
    """Verify validate_bundle_detailed flags missing internal Encounter as WARNING."""
    bundle = {
        "resourceType": "Bundle",
        "id": "b-warn",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "patient-1",
                    "name": [{"family": "One"}],
                }
            },
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-dangling",
                    "status": "current",
                    "subject": {"reference": "Patient/patient-1"},
                    "context": {"encounter": [{"reference": "Encounter/missing-encounter-999"}]},
                    "content": [{"attachment": {"contentType": "text/plain", "data": "VGVzdA=="}}],
                }
            },
        ],
    }

    report = FHIRValidator.validate_bundle_detailed(bundle, expected_patient_id="patient-1")

    # Should have warning for dangling encounter
    warn = next((i for i in report.issues if i.error_code == "UNRESOLVED_INTERNAL_REFERENCE"), None)
    assert warn is not None
    assert warn.severity == ValidationSeverity.WARNING
    assert "missing-encounter-999" in warn.description


def test_validator_bundle_cross_patient_without_patient_resource():
    """Verify validator flags cross-patient leakage even when primary Patient resource is omitted."""
    bundle = {
        "resourceType": "Bundle",
        "id": "b-no-pat-cross",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-pat-1",
                    "status": "current",
                    "subject": {"reference": "Patient/pat-001"},
                    "content": [{"attachment": {"contentType": "text/plain", "data": "VGVzdA=="}}],
                }
            },
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-pat-2",
                    "status": "current",
                    "subject": {"reference": "Patient/pat-002-FOREIGN"},
                    "content": [{"attachment": {"contentType": "text/plain", "data": "VGVzdA=="}}],
                }
            },
        ],
    }

    report = FHIRValidator.validate_bundle_detailed(bundle)
    assert report.status == ValidationStatus.INVALID
    leak_issue = next(
        (i for i in report.issues if i.error_code == "CROSS_PATIENT_REFERENCE_VIOLATION"),
        None,
    )
    assert leak_issue is not None
    assert leak_issue.severity == ValidationSeverity.ERROR


def test_validator_subject_dict_missing_reference():
    """Verify validator flags clinical resources where subject dict is missing the reference key."""
    doc = {
        "resourceType": "DocumentReference",
        "id": "doc-no-ref-key",
        "status": "current",
        "subject": {"display": "Unlinked Patient"},  # Missing 'reference'
        "content": [{"attachment": {"contentType": "text/plain", "data": "VGVzdA=="}}],
    }
    issues = FHIRValidator.validate_resource_detailed(doc)
    # When validating within bundle or standalone:
    bundle = {
        "resourceType": "Bundle",
        "id": "b-sub-missing",
        "type": "collection",
        "entry": [{"resource": doc}],
    }
    rep = FHIRValidator.validate_bundle_detailed(bundle, expected_patient_id="pat-expected")
    err = next((i for i in rep.issues if i.error_code == "MISSING_SUBJECT_REFERENCE"), None)
    assert err is not None
    assert err.severity == ValidationSeverity.ERROR
