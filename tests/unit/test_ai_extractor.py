"""Unit tests for FHIR Clinical Data Extraction and Referential Resolution."""

import base64
import pytest

from app.ai.extractor import FHIRClinicalExtractor


def test_extract_patient_demographics_and_age():
    """Verify patient demographic extraction, age calculation, and gender normalization."""
    extractor = FHIRClinicalExtractor()
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-100",
                    "identifier": [{"system": "http://hospital.org/mrn", "value": "MRN-100"}],
                    "name": [{"family": "Smith", "given": ["Jane"]}],
                    "gender": "female",
                    "birthDate": "1990-05-15",
                }
            }
        ],
    }

    record = extractor.extract_from_bundle(bundle)
    assert record.patient.id == "pat-100"
    assert record.patient.mrn == "MRN-100"
    assert record.patient.gender == "female"
    assert record.patient.date_of_birth == "1990-05-15"
    assert record.patient.age_years is not None
    assert record.patient.age_years >= 30
    assert record.patient.source_reference == "Patient/pat-100"


def test_extract_unordered_bundle_resources():
    """Verify extractor does not rely on bundle resource ordering."""
    extractor = FHIRClinicalExtractor()
    # DiagnosticReport before Patient, Observation at the very end
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "DiagnosticReport",
                    "id": "dr-1",
                    "code": {"text": "Complete Blood Count"},
                    "category": [{"coding": [{"code": "LAB"}]}],
                    "result": [{"reference": "Observation/obs-hb"}],
                    "conclusion": "Mild microcytic anemia",
                }
            },
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-200",
                    "identifier": [{"value": "MRN-200"}],
                    "gender": "male",
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-1",
                    "code": {"text": "Type 2 Diabetes Mellitus"},
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "verificationStatus": {"coding": [{"code": "confirmed"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-hb",
                    "code": {"text": "Hemoglobin"},
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "valueQuantity": {"value": 9.5, "unit": "g/dL"},
                    "referenceRange": [{"low": {"value": 12.0}, "high": {"value": 16.0}}],
                    "interpretation": [{"coding": [{"code": "L"}]}],
                }
            },
        ],
    }

    record = extractor.extract_from_bundle(bundle)
    assert record.patient.id == "pat-200"
    assert len(record.conditions) == 1
    assert record.conditions[0].name == "Type 2 Diabetes Mellitus"
    assert len(record.observations) == 1
    assert record.observations[0].name == "Hemoglobin"
    assert record.observations[0].is_abnormal is True
    assert record.observations[0].numeric_value == 9.5

    assert len(record.diagnostic_reports) == 1
    assert record.diagnostic_reports[0].observation_ids == ["obs-hb"]
    assert "Patient/pat-200" in record.source_references
    assert "Observation/obs-hb" in record.source_references
    assert "DiagnosticReport/dr-1" in record.source_references
    assert "Condition/cond-1" in record.source_references


def test_extract_abnormal_observations_and_reference_ranges():
    """Verify anomaly detection for out-of-range observations and abnormal interpretation flags."""
    extractor = FHIRClinicalExtractor()
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-300",
                    "gender": "male",
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-glu",
                    "code": {"text": "Fasting Plasma Glucose"},
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "valueQuantity": {"value": 245.0, "unit": "mg/dL"},
                    "referenceRange": [{"low": {"value": 70.0}, "high": {"value": 99.0}, "text": "70-99 mg/dL"}],
                    "interpretation": [{"coding": [{"code": "H"}]}],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-na",
                    "code": {"text": "Serum Sodium"},
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "valueQuantity": {"value": 140.0, "unit": "mmol/L"},
                    "referenceRange": [{"low": {"value": 135.0}, "high": {"value": 145.0}}],
                    "interpretation": [{"coding": [{"code": "N"}]}],
                }
            },
        ],
    }

    record = extractor.extract_from_bundle(bundle)
    assert len(record.observations) == 2
    obs_map = {o.id: o for o in record.observations}

    assert obs_map["obs-glu"].is_abnormal is True
    assert obs_map["obs-na"].is_abnormal is False

    assert len(record.flagged_anomalies) >= 1
    anomaly_text = " ".join(record.flagged_anomalies)
    assert "Fasting Plasma Glucose" in anomaly_text
    assert "245.0 mg/dL" in anomaly_text


def test_extract_document_reference_clinical_notes_base64():
    """Verify DocumentReference content extraction with base64 decoding."""
    extractor = FHIRClinicalExtractor()
    note_text = "CHIEF COMPLAINT: Persistent acute chest tightness and dyspnea."
    encoded_b64 = base64.b64encode(note_text.encode("utf-8")).decode("utf-8")

    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-400",
                    "gender": "female",
                }
            },
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-01",
                    "description": "Emergency Department Admission Note",
                    "date": "2026-11-20T14:30:00Z",
                    "content": [
                        {
                            "attachment": {
                                "contentType": "text/plain",
                                "data": encoded_b64,
                            }
                        }
                    ],
                }
            },
        ],
    }

    record = extractor.extract_from_bundle(bundle)
    assert len(record.clinical_notes) == 1
    assert "chest tightness and dyspnea" in record.clinical_notes[0].content_text
    assert record.chief_concern == "Persistent acute chest tightness and dyspnea"


def test_detect_conflicting_condition_records():
    """Verify detection of conflicting active and resolved conditions for the same entity."""
    extractor = FHIRClinicalExtractor()
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {"resourceType": "Patient", "id": "pat-500", "gender": "male"}
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c1",
                    "code": {"text": "Atrial Fibrillation"},
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c2",
                    "code": {"text": "Atrial Fibrillation"},
                    "clinicalStatus": {"coding": [{"code": "resolved"}]},
                }
            },
        ],
    }

    record = extractor.extract_from_bundle(bundle)
    assert len(record.conditions) == 2
    conflicts = [a for a in record.flagged_anomalies if "Conflicting" in a]
    assert len(conflicts) == 1
    assert "Atrial Fibrillation" in conflicts[0]
