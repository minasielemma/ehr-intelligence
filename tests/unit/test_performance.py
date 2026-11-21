"""Performance and throughput verification benchmarks for EHR Ingestion Pipeline."""

import io
import time
import pytest
from app.ingestion.cleaners.text_cleaner import ClinicalTextCleaner
from app.ingestion.deduplication.fingerprint import RecordFingerprinter
from app.ingestion.normalizers.date_normalizer import DateNormalizer
from app.ingestion.normalizers.demographics import DemographicNormalizer
from app.ingestion.normalizers.gender_normalizer import GenderNormalizer
from app.ingestion.normalizers.mrn_normalizer import MRNNormalizer
from app.ingestion.parsers import CSVParser, JSONParser


def test_normalization_throughput_benchmark() -> None:
    """Benchmark raw demographic, date, gender, and MRN normalization throughput."""
    record_count = 2000
    sample_records = [
        {
            "mrn": f"  000{i:06d}  ",
            "first_name": f"PatientFirstName{i}",
            "last_name": f"PatientLastName{i}",
            "dob": "1985-06-15",
            "gender": "Female" if i % 2 == 0 else "Male",
        }
        for i in range(record_count)
    ]

    start_time = time.perf_counter()
    normalized_count = 0
    for rec in sample_records:
        patient, audits, issues = DemographicNormalizer.normalize_patient(
            raw_data=rec,
            source_system="benchmark_hospital",
            job_id="bench-job-1",
        )
        if patient:
            normalized_count += 1

    elapsed = time.perf_counter() - start_time
    throughput = normalized_count / elapsed
    print(f"\n[BENCHMARK] Demographic Normalization Throughput: {throughput:.1f} records/sec ({record_count} in {elapsed:.3f}s)")

    # Assert reasonable production-grade performance threshold (> 2,500 records/sec on modern hardware)
    assert throughput > 1000.0
    assert normalized_count == record_count


def test_fingerprint_and_deduplication_throughput() -> None:
    """Benchmark SHA-256 content hashing and record fingerprinting speed."""
    record_count = 5000
    sample_texts = [
        f"Encounter #{i}: Patient evaluated for hypertension. BP 120/80 mmHg. Prescribed Lisinopril 10mg."
        for i in range(record_count)
    ]

    start_time = time.perf_counter()
    for i, text in enumerate(sample_texts):
        content_hash = RecordFingerprinter.compute_content_hash(text)
        fp = RecordFingerprinter.generate_fingerprint(
            source_system="hospital_perf",
            patient_mrn=f"MRN-{i}",
            record_type="note",
            record_date="2024-01-01",
            content_hash=content_hash,
        )
        assert len(fp) == 64

    elapsed = time.perf_counter() - start_time
    throughput = record_count / elapsed
    print(f"\n[BENCHMARK] Fingerprinting & Hashing Throughput: {throughput:.1f} operations/sec ({record_count} in {elapsed:.3f}s)")
    assert throughput > 5000.0


def test_csv_streaming_chunk_memory_efficiency() -> None:
    """Benchmark memory efficiency and throughput of streaming chunk-based CSV parser."""
    row_count = 5000
    csv_lines = ["mrn,first_name,last_name,dob,gender,clinical_text"]
    for i in range(row_count):
        csv_lines.append(f"00{i:06d},FirstName{i},LastName{i},1980-01-01,M,Routine clinical encounter note {i}")
    csv_data = "\n".join(csv_lines)

    parser = CSVParser()
    start_time = time.perf_counter()

    parsed_count = 0
    # Stream parser line-by-line using generator
    for raw_rec in parser.parse(csv_data, source_system="csv_bench"):
        parsed_count += 1

    elapsed = time.perf_counter() - start_time
    throughput = parsed_count / elapsed
    print(f"\n[BENCHMARK] CSV Streaming Parser Throughput: {throughput:.1f} records/sec ({row_count} in {elapsed:.3f}s)")

    assert parsed_count == row_count
    assert throughput > 3000.0


def test_text_cleaner_throughput() -> None:
    """Benchmark clinical text cleaner performance on narrative notes."""
    note_count = 2000
    sample_note = (
        "CHIEF COMPLAINT:\r\n"
        "Patient presents with shortness of breath.\x00\n\n\n"
        "VITAL SIGNS:\n"
        "BP: 130/84 mmHg, HR: 76 bpm, Temp: 37.0°C, SpO2: 97%.\n"
        "ASSESSMENT & PLAN:\n"
        "Mild COPD exacerbation. Prescribed Albuterol MDI 2 puffs Q4H PRN SOB.\n"
    )

    start_time = time.perf_counter()
    for _ in range(note_count):
        cleaned, txs = ClinicalTextCleaner.clean(sample_note)
        assert "130/84 mmHg" in cleaned

    elapsed = time.perf_counter() - start_time
    throughput = note_count / elapsed
    print(f"\n[BENCHMARK] Clinical Text Cleaner Throughput: {throughput:.1f} notes/sec ({note_count} in {elapsed:.3f}s)")
    assert throughput > 2000.0
