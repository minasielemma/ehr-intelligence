"""Unit tests for JSON, CSV, and Plain-Text EHR input parsers."""

import io
import pytest
from app.core.exceptions import ValidationException
from app.ingestion.parsers import CSVParser, JSONParser, TextParser, get_parser_for_format
from app.schemas.canonical import MappingProfile


def test_get_parser_factory() -> None:
    """Verify parser registry returns correct parser instances and rejects invalid formats."""
    assert isinstance(get_parser_for_format("json"), JSONParser)
    assert isinstance(get_parser_for_format("csv"), CSVParser)
    assert isinstance(get_parser_for_format("text"), TextParser)
    assert isinstance(get_parser_for_format(".txt"), TextParser)

    with pytest.raises(ValidationException):
        get_parser_for_format("unsupported_format_xyz")


def test_json_parser_array() -> None:
    """Verify parsing a JSON array of patient records."""
    data = """
    [
        {
            "id": "REC-001",
            "mrn": "MRN-1001",
            "first_name": "Jane",
            "last_name": "Doe",
            "dob": "1980-05-12",
            "gender": "female",
            "clinical_text": "Patient presents for annual routine wellness exam."
        },
        {
            "id": "REC-002",
            "mrn": "MRN-1002",
            "first_name": "John",
            "last_name": "Smith",
            "dob": "1975-11-23",
            "gender": "male",
            "clinical_text": "Follow-up for hypertension management. BP 128/82 mmHg."
        }
    ]
    """
    parser = JSONParser()
    records = list(parser.parse(data, source_system="general_hospital"))
    assert len(records) == 2
    assert records[0].source_record_id == "REC-001"
    assert records[0].raw_patient["first_name"] == "Jane"
    assert records[0].raw_patient["mrn"] == "MRN-1001"
    assert "wellness exam" in records[0].raw_document

    assert records[1].source_record_id == "REC-002"
    assert records[1].raw_patient["last_name"] == "Smith"


def test_json_parser_nested_mapping() -> None:
    """Verify parsing nested JSON EHR export using custom mapping profile."""
    data = """
    {
        "patients": [
            {
                "record_id": "NEST-01",
                "patient": {
                    "demographics": {
                        "identifier": "MRN-8888",
                        "name": {
                            "given": "Alice",
                            "family": "Wonder"
                        },
                        "birth_date": "1992-07-15",
                        "sex": "F"
                    }
                },
                "encounter": {
                    "date": "2023-04-10T14:30:00Z",
                    "type": "consultation",
                    "notes": "Patient in no acute distress. Continues Metformin 500mg BID."
                }
            }
        ]
    }
    """
    mapping = MappingProfile(
        source_system="epic_system",
        mrn_field="patient.demographics.identifier",
        first_name_field="patient.demographics.name.given",
        last_name_field="patient.demographics.name.family",
        dob_field="patient.demographics.birth_date",
        gender_field="patient.demographics.sex",
        record_date_field="encounter.date",
        record_type_field="encounter.type",
        content_field="encounter.notes",
    )
    parser = JSONParser()
    records = list(parser.parse(data, source_system="epic_system", mapping_profile=mapping))
    assert len(records) == 1
    rec = records[0]
    assert rec.source_record_id == "NEST-01"
    assert rec.raw_patient["patient.demographics.identifier"] == "MRN-8888"
    assert rec.raw_patient["patient.demographics.name.given"] == "Alice"
    assert rec.raw_patient["patient.demographics.name.family"] == "Wonder"
    assert rec.raw_patient["patient.demographics.birth_date"] == "1992-07-15"
    assert "Metformin 500mg" in rec.raw_document


def test_json_parser_malformed_syntax() -> None:
    """Verify malformed JSON syntax raises ValidationException."""
    parser = JSONParser()
    with pytest.raises(ValidationException):
        list(parser.parse("{invalid_json: true,", source_system="test"))


def test_csv_parser_standard_and_delimiters() -> None:
    """Verify CSV parser correctly parses comma, semicolon, and pipe-delimited data."""
    csv_comma = (
        "mrn,first_name,last_name,dob,gender,clinical_text\n"
        "00123,David,Miller,1968-03-21,male,Complains of chronic back pain.\n"
        "00124,Sarah,Connor,1985-09-12,female,Routine evaluation post-operative.\n"
    )
    parser = CSVParser()
    records = list(parser.parse(csv_comma, source_system="clinic_a"))
    assert len(records) == 2
    assert records[0].raw_patient["mrn"] == "00123"
    assert records[0].raw_patient["first_name"] == "David"
    assert records[0].raw_patient["last_name"] == "Miller"
    assert records[1].raw_patient["mrn"] == "00124"

    # Semicolon delimited
    csv_semicolon = (
        "mrn;first_name;last_name;dob;gender;clinical_text\n"
        "00555;Marcus;Vance;1977-01-30;M;Cardiac checkup. EKG normal.\n"
    )
    records_semi = list(parser.parse(csv_semicolon, source_system="clinic_b"))
    assert len(records_semi) == 1
    assert records_semi[0].raw_patient["mrn"] == "00555"
    assert records_semi[0].raw_patient["first_name"] == "Marcus"


def test_csv_parser_quoted_multiline_fields() -> None:
    """Verify CSV parser preserves quoted fields with internal commas and newlines."""
    csv_quoted = (
        'mrn,first_name,last_name,dob,gender,clinical_text\n'
        '00999,Robert,Taylor,1954-12-05,M,"Physical Exam:\nHeart: RRR, no murmurs.\nLungs: Clear to auscultation bilaterally."\n'
    )
    parser = CSVParser()
    records = list(parser.parse(csv_quoted, source_system="clinic_c"))
    assert len(records) == 1
    assert "Heart: RRR" in records[0].raw_document
    assert "Clear to auscultation" in records[0].raw_document


def test_csv_parser_encoding_fallback() -> None:
    """Verify CSV parser handles Latin-1 encoded characters correctly."""
    latin1_bytes = (
        "mrn,first_name,last_name,dob,gender,clinical_text\n"
        "00777,René,Müller,1962-08-14,male,Patient feels well.\n"
    ).encode("latin-1")

    parser = CSVParser()
    records = list(parser.parse(latin1_bytes, source_system="international_clinic"))
    assert len(records) == 1
    assert records[0].raw_patient["first_name"] == "René"
    assert records[0].raw_patient["last_name"] == "Müller"


def test_text_parser_structured_clinical_note() -> None:
    """Verify TextParser extracts clinical document headers while preserving narrative body."""
    text_note = """
    PATIENT NAME: Doe, Emily
    MRN: 9948201
    DOB: 1989-10-04
    GENDER: Female
    DATE: 2024-02-15
    REPORT TYPE: Discharge Summary

    HISTORY OF PRESENT ILLNESS:
    The patient is a 34-year-old female admitted with acute uncomplicated appendicitis.
    Underwent successful laparoscopic appendectomy on 2024-02-13.
    Post-operative course was unremarkable.
    Discharged in stable condition.
    """
    parser = TextParser()
    records = list(parser.parse(text_note, source_system="hospital_ward"))
    assert len(records) == 1
    rec = records[0]
    assert rec.raw_patient["mrn"] == "9948201"
    assert rec.raw_patient["first_name"] == "Emily"
    assert rec.raw_patient["last_name"] == "Doe"
    assert rec.raw_patient["dob"] == "1989-10-04"
    assert rec.raw_patient["gender"] == "Female"
    assert rec.metadata["record_type"] == "Discharge Summary"
    assert "laparoscopic appendectomy" in rec.raw_document


def test_csv_parser_domain_detection_provenance() -> None:
    """Verify CSVParser detects provenances domain from headers without requiring patient names."""
    csv_prov = (
        "provenance_id,patient_id,target_resource_type,target_resource_id,recorded_at,agent_id,activity,signature_status\n"
        "PROV-000001,PAT-000001,Patient,PAT-000001,2026-11-21T00:00:00,SYSTEM-SYNTHETIC,record-generation,not-signed-synthetic\n"
    )
    parser = CSVParser()
    records = list(parser.parse(csv_prov, source_system="audit_sys"))
    assert len(records) == 1
    assert records[0].metadata["domain"] == "provenances"
    assert records[0].source_record_id == "PROV-000001"
    assert records[0].metadata["raw_row"]["patient_id"] == "PAT-000001"


def test_extract_patient_reference_formats() -> None:
    """Verify IngestionOrchestrator.extract_patient_reference extracts patient IDs from diverse formats."""
    from app.ingestion.orchestrator import IngestionOrchestrator
    from app.schemas.canonical import RawRecord

    # 1. Direct patient_id in raw_data
    assert IngestionOrchestrator.extract_patient_reference({"patient_id": "P-100"}) == "P-100"

    # 2. Scoped FHIR reference
    assert IngestionOrchestrator.extract_patient_reference({"subject": "Patient/P-200"}) == "P-200"

    # 3. Nested dictionary reference
    assert IngestionOrchestrator.extract_patient_reference({"subject": {"reference": "Patient/P-300"}}) == "P-300"

    # 4. Beneficiary / Member identifier
    assert IngestionOrchestrator.extract_patient_reference({"beneficiary_id": "BEN-400"}) == "BEN-400"

    # 5. Target resource in provenance
    assert IngestionOrchestrator.extract_patient_reference({"target_resource_type": "Patient", "target_resource_id": "PAT-500"}) == "PAT-500"

    # 6. From RawRecord raw_patient
    raw_rec = RawRecord(
        source_record_id="REC-01",
        source_system="ehr",
        raw_patient={"mrn": "MRN-600"},
        raw_document="Sample",
        metadata={},
    )
    assert IngestionOrchestrator.extract_patient_reference(raw_rec=raw_rec) == "MRN-600"
