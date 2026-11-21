"""Unit tests for FHIR R4 validator, mapper, and parser components."""

import json
import pytest

from app.core.exceptions import ValidationException
from app.fhir.mapper import FHIRMapper, extract_reference_id
from app.fhir.validator import FHIRValidator
from app.ingestion.parsers.fhir_parser import FHIRParser


def test_extract_reference_id():
    """Test extracting resource ID from various FHIR reference string formats."""
    assert extract_reference_id("Patient/12345") == "12345"
    assert extract_reference_id("Encounter/ENC-99") == "ENC-99"
    assert extract_reference_id("urn:uuid:550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"
    assert extract_reference_id("12345") == "12345"
    assert extract_reference_id(None) is None
    assert extract_reference_id("") is None


def test_fhir_validator_patient_valid():
    """Verify FHIRValidator approves compliant FHIR R4 Patient resource."""
    valid_patient = {
        "resourceType": "Patient",
        "id": "pat-100",
        "identifier": [
            {
                "system": "http://hospital.example.org/mrn",
                "value": "MRN-100",
                "type": {"coding": [{"code": "MR"}]},
            }
        ],
        "name": [{"family": "Smith", "given": ["Jane"]}],
        "gender": "female",
        "birthDate": "1985-04-12",
    }
    is_valid, err = FHIRValidator.validate_resource(valid_patient)
    assert is_valid is True
    assert err is None


def test_fhir_validator_invalid_resource():
    """Verify FHIRValidator catches missing resourceType or invalid structure."""
    is_valid, err = FHIRValidator.validate_resource({"id": "no-type"})
    assert is_valid is False
    assert "Missing required 'resourceType'" in err

    is_valid, err = FHIRValidator.validate_resource("not-a-dict")
    assert is_valid is False
    assert "JSON object" in err

    is_valid, err = FHIRValidator.validate_resource({"resourceType": "NonExistentResource123"})
    assert is_valid is False
    assert "Unsupported" in err


def test_fhir_validator_bundle_validation():
    """Verify validation of FHIR R4 Bundle containing mixed resources."""
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p1",
                    "name": [{"family": "Doe", "given": ["John"]}],
                    "gender": "male",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "e1",
                    "status": "finished",
                    "class": {"code": "AMB", "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode"},
                    "subject": {"reference": "Patient/p1"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs1",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                    "subject": {"reference": "Patient/p1"},
                    "valueQuantity": {"value": 75.0, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"},
                }
            },
        ],
    }
    all_valid, valid_count, errors = FHIRValidator.validate_bundle(bundle)
    assert all_valid is True
    assert valid_count == 3
    assert len(errors) == 0


def test_fhir_mapper_comprehensive_domains():
    """Verify FHIRMapper accurately translates diverse FHIR R4 resources to canonical domain dictionaries."""
    # 1. Patient
    pat_res = {
        "resourceType": "Patient",
        "id": "pat-01",
        "identifier": [{"system": "http://hospital.example.org/mrn", "value": "MRN-001"}],
        "name": [{"family": "Williams", "given": ["Robert", "J."]}],
        "gender": "male",
        "birthDate": "1972-11-23",
        "telecom": [{"system": "phone", "value": "555-0192"}],
    }
    domain, entity = FHIRMapper.to_canonical_entity(pat_res, source_system="test_ehr")
    assert domain == "patients"
    assert entity["mrn"] == "MRN-001"
    assert entity["first_name"] == "Robert"
    assert entity["middle_name"] == "J."
    assert entity["last_name"] == "Williams"
    assert entity["administrative_gender"] == "male"
    assert entity["date_of_birth"] == "1972-11-23"

    # 2. Encounter
    enc_res = {
        "resourceType": "Encounter",
        "id": "enc-01",
        "status": "finished",
        "class": {"code": "IMP"},
        "subject": {"reference": "Patient/pat-01"},
        "period": {"start": "2024-02-01T08:00:00Z", "end": "2024-02-03T12:00:00Z"},
        "reasonCode": [{"coding": [{"code": "I10", "display": "Hypertension"}]}],
    }
    domain, entity = FHIRMapper.to_canonical_entity(enc_res)
    assert domain == "encounters"
    assert entity["source_id"] == "enc-01"
    assert entity["patient_source_id"] == "pat-01"
    assert entity["class_code"] == "IMP"
    assert entity["reason_code"] == "I10"

    # 3. Condition
    cond_res = {
        "resourceType": "Condition",
        "id": "cond-01",
        "subject": {"reference": "Patient/pat-01"},
        "encounter": {"reference": "Encounter/enc-01"},
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9", "display": "Type 2 Diabetes"}]},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "verificationStatus": {"coding": [{"code": "confirmed"}]},
    }
    domain, entity = FHIRMapper.to_canonical_entity(cond_res)
    assert domain == "conditions"
    assert entity["patient_source_id"] == "pat-01"
    assert entity["encounter_source_id"] == "enc-01"
    assert entity["code"] == "E11.9"
    assert entity["display"] == "Type 2 Diabetes"

    # 4. Observation
    obs_res = {
        "resourceType": "Observation",
        "id": "obs-01",
        "status": "final",
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic BP"}]},
        "subject": {"reference": "Patient/pat-01"},
        "valueQuantity": {"value": 128.0, "unit": "mmHg"},
    }
    domain, entity = FHIRMapper.to_canonical_entity(obs_res)
    assert domain == "observations"
    assert entity["code"] == "8480-6"
    assert entity["value_quantity"] == 128.0
    assert entity["value_unit"] == "mmHg"

    # 5. MedicationRequest
    med_res = {
        "resourceType": "MedicationRequest",
        "id": "med-01",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "866439", "display": "Metformin 500mg"}]},
        "subject": {"reference": "Patient/pat-01"},
        "encounter": {"reference": "Encounter/enc-01"},
    }
    domain, entity = FHIRMapper.to_canonical_entity(med_res)
    assert domain == "medication_requests"
    assert entity["code"] == "866439"
    assert entity["display"] == "Metformin 500mg"


def test_fhir_parser_bundle():
    """Verify FHIRParser streaming iteration over a transaction bundle."""
    parser = FHIRParser()
    bundle_json = json.dumps({
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p-99",
                    "identifier": [{"value": "MRN-99"}],
                    "name": [{"family": "Taylor", "given": ["Alex"]}],
                    "gender": "other",
                    "birthDate": "1992-06-15",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "enc-99",
                    "status": "finished",
                    "class": {"code": "AMB"},
                    "subject": {"reference": "Patient/p-99"},
                }
            },
        ],
    })
    records = list(parser.parse(bundle_json, source_system="test_fhir"))
    assert len(records) == 2

    # First record should be Patient
    r1 = records[0]
    assert r1.source_record_id == "p-99"
    assert r1.source_format == "fhir"
    assert r1.raw_patient["mrn"] == "MRN-99"
    assert r1.metadata["domain"] == "patients"

    # Second record should be Encounter
    r2 = records[1]
    assert r2.source_record_id == "enc-99"
    assert r2.metadata["domain"] == "encounters"
    assert r2.metadata["entity"]["patient_source_id"] == "p-99"


def test_fhir_parser_ndjson_streaming():
    """Verify FHIRParser parses line-by-line streaming NDJSON files."""
    parser = FHIRParser()
    ndjson_content = (
        json.dumps({"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}], "gender": "female"}) + "\n"
        + json.dumps({"resourceType": "Patient", "id": "p2", "name": [{"family": "B"}], "gender": "male"}) + "\n"
        + json.dumps({"resourceType": "Patient", "id": "p3", "name": [{"family": "C"}], "gender": "unknown"}) + "\n"
    )

    records = list(parser.parse(ndjson_content, source_system="ndjson_system"))
    assert len(records) == 3
    assert records[0].source_record_id == "p1"
    assert records[1].source_record_id == "p2"
    assert records[2].source_record_id == "p3"
    assert all(r.source_format == "fhir" for r in records)
