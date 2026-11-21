"""Unit tests for deterministic record fingerprinting and duplicate classification."""

import pytest
from app.ingestion.deduplication.fingerprint import RecordFingerprinter


def test_fingerprint_determinism() -> None:
    """Verify that identical inputs produce exactly the same SHA-256 fingerprint."""
    content_hash = RecordFingerprinter.compute_content_hash("Patient in no acute distress.")
    fp1 = RecordFingerprinter.generate_fingerprint(
        source_system="hospital_x",
        patient_mrn="MRN-123",
        record_type="progress_note",
        record_date="2023-05-10T10:00:00Z",
        content_hash=content_hash,
        source_record_id="REC-001",
    )
    fp2 = RecordFingerprinter.generate_fingerprint(
        source_system="hospital_x",
        patient_mrn="MRN-123",
        record_type="progress_note",
        record_date="2023-05-10T10:00:00Z",
        content_hash=content_hash,
        source_record_id="REC-001",
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_fingerprint_sensitivity_to_modifications() -> None:
    """Verify changes in clinical content alter the resulting fingerprint."""
    hash_a = RecordFingerprinter.compute_content_hash("Aspirin 81mg PO daily.")
    hash_b = RecordFingerprinter.compute_content_hash("Aspirin 325mg PO daily.")
    assert hash_a != hash_b

    fp_a = RecordFingerprinter.generate_fingerprint(
        source_system="hospital_x",
        patient_mrn="MRN-123",
        record_type="medication",
        record_date="2023-05-10",
        content_hash=hash_a,
    )
    fp_b = RecordFingerprinter.generate_fingerprint(
        source_system="hospital_x",
        patient_mrn="MRN-123",
        record_type="medication",
        record_date="2023-05-10",
        content_hash=hash_b,
    )
    assert fp_a != fp_b


def test_classify_record_duplicate_vs_update() -> None:
    """Verify classification between exact duplicates and legitimate updates."""
    content_a = RecordFingerprinter.compute_content_hash("Routine blood test.")
    content_b = RecordFingerprinter.compute_content_hash("Updated blood test results.")

    fp_a = RecordFingerprinter.generate_fingerprint("sys", "MRN-1", "lab", "2023-01-01", content_a)
    fp_b = RecordFingerprinter.generate_fingerprint("sys", "MRN-1", "lab", "2023-01-01", content_b)

    # Case 1: Exact duplicate
    classification, reason = RecordFingerprinter.classify_record_duplicate_or_update(
        existing_fingerprint=fp_a,
        incoming_fingerprint=fp_a,
        existing_content_hash=content_a,
        incoming_content_hash=content_a,
    )
    assert classification == "EXACT_DUPLICATE"

    # Case 2: Content updated
    classification, reason = RecordFingerprinter.classify_record_duplicate_or_update(
        existing_fingerprint=fp_a,
        incoming_fingerprint=fp_b,
        existing_content_hash=content_a,
        incoming_content_hash=content_b,
    )
    assert classification == "VALID_UPDATE"
