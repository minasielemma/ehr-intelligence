"""Unit tests for HL7 FHIR R4 resource mapping engine (FHIRMapper)."""

import base64
import pytest

from app.fhir.mapper import FHIRMapper, extract_reference_id
from app.schemas.canonical import CanonicalClinicalRecord, CanonicalPatient


def test_map_patient_full_demographics():
    """Verify FHIRMapper accurately translates complete canonical patient demographics."""
    canonical_patient = CanonicalPatient(
        id="pat-uuid-101",
        source_system="hospital_alpha",
        source_patient_id="ALPHA-99",
        mrn="MRN-10123",
        original_mrn="  mrn-10123  ",
        first_name="Eleanor",
        middle_name="Grace",
        last_name="Vance",
        date_of_birth="1978-11-23",
        original_date_of_birth="11/23/1978",
        administrative_gender="female",
        original_gender="F",
        contact_info={
            "phone": "555-0144",
            "email": "eleanor.vance@example.com",
            "address": {
                "street": "1042 Elm Street",
                "city": "Springfield",
                "state": "IL",
                "zip": "62701",
            },
        },
    )

    fhir_patient = FHIRMapper.to_fhir_patient(canonical_patient)

    assert fhir_patient["resourceType"] == "Patient"
    assert fhir_patient["id"] == "pat-uuid-101"
    assert fhir_patient["active"] is True

    # Identifiers: MRN and source patient ID
    identifiers = fhir_patient["identifier"]
    assert len(identifiers) == 2
    mrn_ident = next(i for i in identifiers if i.get("type", {}).get("text") == "MRN")
    assert mrn_ident["value"] == "MRN-10123"
    assert "mrn" in mrn_ident["system"]

    # Name mapping
    names = fhir_patient["name"]
    assert len(names) == 1
    assert names[0]["family"] == "Vance"
    assert names[0]["given"] == ["Eleanor", "Grace"]
    assert names[0]["use"] == "official"

    # Gender & Birthdate
    assert fhir_patient["gender"] == "female"
    assert fhir_patient["birthDate"] == "1978-11-23"

    # Telecom & Address
    assert len(fhir_patient["telecom"]) == 2
    assert fhir_patient["telecom"][0]["value"] == "555-0144"
    assert fhir_patient["address"][0]["city"] == "Springfield"
    assert fhir_patient["address"][0]["postalCode"] == "62701"


def test_map_patient_gender_normalization():
    """Verify robust administrative gender normalization across non-standard inputs."""
    variants = [
        ("M", "male"),
        ("male", "male"),
        ("1", "male"),
        ("F", "female"),
        ("female", "female"),
        ("2", "female"),
        ("other", "other"),
        ("unknown", "unknown"),
        ("nonbinary", "unknown"),
        (None, "unknown"),
    ]

    for raw, expected in variants:
        p_dict = {
            "id": "p-1",
            "mrn": "M1",
            "first_name": "Test",
            "last_name": "User",
            "administrative_gender": raw,
        }
        mapped = FHIRMapper.to_fhir_patient(p_dict)
        assert mapped["gender"] == expected, f"Failed for raw gender '{raw}': expected '{expected}', got '{mapped['gender']}'"


def test_map_patient_missing_optional_fields():
    """Verify mapping handles patients with only minimal required fields without crashing."""
    minimal_patient = {
        "id": "min-pat-1",
        "mrn": "MRN-MIN",
        "first_name": "John",
        "last_name": "Doe",
    }
    mapped = FHIRMapper.to_fhir_patient(minimal_patient)
    assert mapped["resourceType"] == "Patient"
    assert mapped["id"] == "min-pat-1"
    assert mapped["name"][0]["family"] == "Doe"
    assert mapped["name"][0]["given"] == ["John"]
    assert mapped["gender"] == "unknown"
    assert "birthDate" not in mapped
    assert "telecom" not in mapped


def test_map_document_reference_clinical_note():
    """Verify DocumentReference mapping with base64 attachment, metadata, and patient reference."""
    note_text = "Patient reports resolution of acute migraines following prescribed therapy."
    record = CanonicalClinicalRecord(
        id="rec-doc-401",
        job_id="job-001",
        patient_id="pat-uuid-101",
        record_type="progress_note",
        fingerprint="sha256-fingerprint-401",
        record_date="2026-11-20T14:30:00Z",
        cleaned_text=note_text,
    )

    doc_ref = FHIRMapper.to_fhir_document_reference(
        record=record,
        patient_id="pat-uuid-101",
        encounter_id="enc-501",
    )

    assert doc_ref["resourceType"] == "DocumentReference"
    assert doc_ref["id"] == "rec-doc-401"
    assert doc_ref["status"] == "current"
    assert doc_ref["docStatus"] == "final"
    assert doc_ref["subject"]["reference"] == "Patient/pat-uuid-101"
    assert doc_ref["context"]["encounter"][0]["reference"] == "Encounter/enc-501"

    # Coding checks
    assert doc_ref["type"]["coding"][0]["system"] == "http://loinc.org"
    assert doc_ref["type"]["coding"][0]["code"] == "11506-3"
    assert doc_ref["category"][0]["coding"][0]["code"] == "clinical-note"

    # Content attachment verification
    content = doc_ref["content"]
    assert len(content) == 1
    attachment = content[0]["attachment"]
    assert attachment["contentType"] == "text/plain; charset=utf-8"
    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
    assert decoded == note_text


def test_map_document_reference_without_encounter():
    """Verify missing encounter does NOT fabricate an encounter reference."""
    record = {
        "id": "doc-no-enc",
        "record_type": "clinical_note",
        "cleaned_text": "Unscheduled ambulatory telephone triage note.",
        "record_date": "2026-11-19",
    }
    doc_ref = FHIRMapper.to_fhir_document_reference(
        record=record,
        patient_id="pat-100",
        encounter_id=None,
    )
    assert doc_ref["subject"]["reference"] == "Patient/pat-100"
    assert "context" not in doc_ref, "Encounter context must not be fabricated when encounter_id is None"


def test_map_diagnostic_report_lab_panel():
    """Verify DiagnosticReport mapping preserving status, LOINC code, and observation results."""
    report_data = {
        "id": "dr-lab-801",
        "status": "final",
        "category": "LAB",
        "code": "24323-8",
        "display": "Comprehensive metabolic 2000 panel",
        "effective_date": "2026-11-21T08:15:00Z",
        "conclusion": "Electrolytes and liver function tests within reference intervals.",
    }

    dr = FHIRMapper.to_fhir_diagnostic_report(
        report=report_data,
        patient_id="pat-uuid-101",
        encounter_id="enc-501",
        observation_ids=["obs-glu-1", "obs-k-2"],
    )

    assert dr["resourceType"] == "DiagnosticReport"
    assert dr["id"] == "dr-lab-801"
    assert dr["status"] == "final"
    assert dr["subject"]["reference"] == "Patient/pat-uuid-101"
    assert dr["encounter"]["reference"] == "Encounter/enc-501"
    assert dr["code"]["coding"][0]["code"] == "24323-8"
    assert len(dr["result"]) == 2
    assert dr["result"][0]["reference"] == "Observation/obs-glu-1"
    assert dr["result"][1]["reference"] == "Observation/obs-k-2"
    assert "Electrolytes" in dr["conclusion"]


def test_map_encounter_and_observation():
    """Verify Encounter and Observation mapping."""
    encounter_data = {
        "id": "enc-901",
        "status": "finished",
        "encounter_class": "AMB",
        "start_date": "2026-11-20T09:00:00Z",
        "end_date": "2026-11-20T09:45:00Z",
        "reason_code": "386661006",
        "reason_display": "Fever",
    }
    enc = FHIRMapper.to_fhir_encounter(encounter_data, patient_id="pat-uuid-101")
    assert enc["resourceType"] == "Encounter"
    assert enc["id"] == "enc-901"
    assert enc["status"] == "finished"
    assert enc["subject"]["reference"] == "Patient/pat-uuid-101"
    assert enc["period"]["start"] == "2026-11-20T09:00:00Z"

    obs_data = {
        "id": "obs-hr-101",
        "code": "8867-4",
        "display": "Heart rate",
        "category": "vital-signs",
        "value_numeric": 72.0,
        "value_unit": "/min",
        "effective_date": "2026-11-20T09:10:00Z",
    }
    obs = FHIRMapper.to_fhir_observation(obs_data, patient_id="pat-uuid-101", encounter_id="enc-901")
    assert obs["resourceType"] == "Observation"
    assert obs["id"] == "obs-hr-101"
    assert obs["subject"]["reference"] == "Patient/pat-uuid-101"
    assert obs["encounter"]["reference"] == "Encounter/enc-901"
    assert obs["valueQuantity"]["value"] == 72.0
    assert obs["valueQuantity"]["unit"] == "/min"


def test_map_observation_model_direct():
    """Verify ObservationModel instances correctly map value_string, unit, and handle empty units."""
    from app.models.ingestion import ObservationModel

    # 1. Text observation with value_string
    obs_text = ObservationModel(
        id="obs-text-01",
        patient_id="pat-uuid-101",
        source_system="hospital_alpha",
        job_id="job-01",
        code="XRAY-FIND",
        display="Chest Findings",
        value_string="Lungs clear bilaterally. No acute cardiopulmonary disease.",
    )
    mapped_text = FHIRMapper.to_fhir_observation(obs_text, patient_id="pat-uuid-101")
    assert mapped_text["valueString"] == "Lungs clear bilaterally. No acute cardiopulmonary disease."
    assert "valueQuantity" not in mapped_text

    # 2. Numeric observation with unit
    obs_num = ObservationModel(
        id="obs-num-02",
        patient_id="pat-uuid-101",
        source_system="hospital_alpha",
        job_id="job-01",
        code="8867-4",
        display="Heart rate",
        value_numeric=82.0,
        unit="bpm",
    )
    mapped_num = FHIRMapper.to_fhir_observation(obs_num, patient_id="pat-uuid-101")
    assert mapped_num["valueQuantity"]["value"] == 82.0
    assert mapped_num["valueQuantity"]["unit"] == "bpm"
    assert mapped_num["valueQuantity"]["code"] == "bpm"

    # 3. Numeric observation without unit (must omit unit/code rather than empty string)
    obs_no_unit = ObservationModel(
        id="obs-num-03",
        patient_id="pat-uuid-101",
        source_system="hospital_alpha",
        job_id="job-01",
        code="2345-7",
        display="Glucose index",
        value_numeric=105.0,
        unit=None,
    )
    mapped_no_unit = FHIRMapper.to_fhir_observation(obs_no_unit, patient_id="pat-uuid-101")
    assert mapped_no_unit["valueQuantity"]["value"] == 105.0
    assert "unit" not in mapped_no_unit["valueQuantity"]
    assert "code" not in mapped_no_unit["valueQuantity"]
