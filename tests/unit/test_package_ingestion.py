"""Unit tests for package extraction security, decompression limits, checksums, and topological sorting."""

import io
import json
from pathlib import Path
import zipfile
import pytest

from app.core.exceptions import ValidationException
from app.ingestion.parsers.package_processor import (
    DOMAIN_INGESTION_RANK,
    PackageProcessor,
)


def test_topological_domain_sequencing():
    """Verify healthcare domain files are assigned correct dependency ranks."""
    files = [
        "claims.csv",
        "encounters.csv",
        "organizations.csv",
        "conditions.csv",
        "patients.csv",
        "practitioners.csv",
        "observations.csv",
        "coverages.csv",
    ]
    ranked = []
    for f in files:
        domain, rank = PackageProcessor.detect_domain(f)
        ranked.append((rank, f, domain))

    ranked.sort(key=lambda x: x[0])
    ordered_filenames = [x[1] for x in ranked]

    # Verify dependency prerequisites
    assert ordered_filenames.index("organizations.csv") < ordered_filenames.index("encounters.csv")
    assert ordered_filenames.index("practitioners.csv") < ordered_filenames.index("encounters.csv")
    assert ordered_filenames.index("patients.csv") < ordered_filenames.index("encounters.csv")
    assert ordered_filenames.index("coverages.csv") < ordered_filenames.index("claims.csv")
    assert ordered_filenames.index("encounters.csv") < ordered_filenames.index("conditions.csv")
    assert ordered_filenames.index("encounters.csv") < ordered_filenames.index("claims.csv")


def test_zip_slip_security_prevention(tmp_path):
    """Verify PackageProcessor rejects ZIP archive attempting directory traversal (ZipSlip)."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Malicious entry attempting to escape extraction directory
        zf.writestr("../../etc/cron.d/malicious", "malicious payload")

    extract_dir = tmp_path / "extracted_attack"
    with pytest.raises(ValidationException) as excinfo:
        PackageProcessor.extract_and_validate(zip_buffer.getvalue(), extract_dir)

    assert "ZipSlip" in str(excinfo.value) or "traversal" in str(excinfo.value)


def test_checksum_mismatch_detection(tmp_path):
    """Verify PackageProcessor catches altered or corrupted files against checksums.sha256."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("patients.csv", "id,mrn,first_name\n1,M1,Alice\n")
        # Provide deliberately wrong sha256 checksum
        zf.writestr("checksums.sha256", "0000000000000000000000000000000000000000000000000000000000000000  patients.csv\n")

    extract_dir = tmp_path / "extracted_corrupted"
    with pytest.raises(ValidationException) as excinfo:
        PackageProcessor.extract_and_validate(zip_buffer.getvalue(), extract_dir)

    assert "Checksum mismatch" in str(excinfo.value) or "Integrity check failed" in str(excinfo.value)


def test_valid_package_extraction_and_manifest(tmp_path):
    """Verify clean extraction, manifest parsing, and sequencing of a valid multi-file EHR archive."""
    import hashlib

    p_content = b"id,mrn,first_name,last_name\n1,M01,Jane,Doe\n"
    e_content = b"id,patient_id,status\nENC-1,M01,finished\n"

    p_sha = hashlib.sha256(p_content).hexdigest()
    e_sha = hashlib.sha256(e_content).hexdigest()

    checksums_txt = f"{p_sha}  patients.csv\n{e_sha}  encounters.csv\n"

    manifest_json = {
        "dataset_name": "Test Hospital Export",
        "provider": "Community General",
        "files": [
            {"filename": "patients.csv", "sha256": p_sha, "domain": "patients"},
            {"filename": "encounters.csv", "sha256": e_sha, "domain": "encounters"},
        ]
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("patients.csv", p_content)
        zf.writestr("encounters.csv", e_content)
        zf.writestr("checksums.sha256", checksums_txt)
        zf.writestr("manifest.json", json.dumps(manifest_json))

    extract_dir = tmp_path / "extracted_valid"
    manifest, files = PackageProcessor.extract_and_validate(zip_buffer.getvalue(), extract_dir)

    assert manifest.dataset_name == "Test Hospital Export"
    assert manifest.hospital_name == "Community General"
    assert len(files) == 2
    assert files[0].filename == "patients.csv"
    assert files[1].filename == "encounters.csv"
    assert files[0].sort_rank < files[1].sort_rank
