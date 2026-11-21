"""Integration tests verifying full-lifecycle ingestion of a comprehensive hospital EHR export.

Validates:
- Multi-format hospital EHR package (CSV domains, consolidated JSON, FHIR R4 Bundle, NDJSON, text notes)
- Scaled dataset with 2,000 synthetic patients and thousands of longitudinal records
- Cross-file foreign-key referential integrity (encounters, conditions, observations, claims, coverages)
- Post-ingestion domain metrics and referential integrity audit report
- Per-file package tracking and idempotency protections
"""

from pathlib import Path
import pytest
from httpx import AsyncClient

from app.models.database import get_session_factory
from app.repositories.domain_repository import DomainRepository
from app.repositories.patient_repository import PatientRepository

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
ZIP_PACKAGE_PATH = FIXTURES_DIR / "hospital_ehr_export_2000.zip"


@pytest.mark.asyncio
async def test_comprehensive_hospital_export_ingestion(async_client: AsyncClient, test_settings):
    """End-to-end integration test ingesting the 2,000 patient hospital EHR export package."""
    assert ZIP_PACKAGE_PATH.exists(), f"Synthetic dataset package not found at {ZIP_PACKAGE_PATH}"

    archive_bytes = ZIP_PACKAGE_PATH.read_bytes()
    idempotency_key = "idemp-comprehensive-hospital-2000"

    # 1. Upload EHR package via API
    response = await async_client.post(
        "/api/v1/ingestion/upload",
        files={"file": ("hospital_ehr_export_2000.zip", archive_bytes, "application/zip")},
        data={
            "source_system": "metropolitan_ehr",
            "idempotency_key": idempotency_key,
            "sync": "true",
        },
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == 201, f"Upload failed: {response.text}"
    job_data = response.json()
    job_id = job_data["job_id"]

    assert job_data["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS"]
    assert job_data["total_records"] >= 2000
    assert job_data["successful_records"] >= 2000

    # 2. Verify database records and domain entities via DomainRepository
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        domain_repo = DomainRepository(session)
        patient_repo = PatientRepository(session)

        # Patient count
        patients = await patient_repo.search_patients(limit=3000)
        assert len(patients) >= 2000, f"Expected at least 2,000 patients, got {len(patients)}"

        # Domain entity counts
        domain_counts = await domain_repo.get_domain_counts_for_job(job_id)
        assert domain_counts.get("encounters", 0) >= 4000
        assert domain_counts.get("conditions", 0) >= 4000
        assert domain_counts.get("observations", 0) >= 10000
        assert domain_counts.get("medication_requests", 0) >= 4000
        assert domain_counts.get("procedures", 0) >= 3000
        assert domain_counts.get("coverages", 0) >= 2000
        assert domain_counts.get("claims", 0) >= 4000
        assert domain_counts.get("allergies", 0) >= 500
        assert domain_counts.get("immunizations", 0) >= 1500
        assert domain_counts.get("organizations", 0) >= 2
        assert domain_counts.get("practitioners", 0) >= 10

        # Referential integrity audit
        integrity = await domain_repo.get_referential_integrity_report(job_id)
        assert integrity["referential_integrity_status"] == "VALID"
        assert integrity["orphan_encounters"] == 0
        assert integrity["orphan_conditions"] == 0
        assert integrity["orphan_observations"] == 0

    # 3. Verify per-file package tracking endpoint
    files_resp = await async_client.get(
        f"/api/v1/ingestion/jobs/{job_id}/files",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert files_resp.status_code == 200
    pkg_files = files_resp.json()
    assert len(pkg_files) >= 10
    # Every package file should be COMPLETED
    for pf in pkg_files:
        assert pf["status"] == "COMPLETED", f"File {pf['file_path']} failed with error: {pf.get('error_message')}"
        assert pf["total_records"] > 0

    # 4. Verify post-ingestion comprehensive report
    report_resp = await async_client.get(
        f"/api/v1/ingestion/jobs/{job_id}/report",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert "domain_summary" in report
    assert "referential_integrity" in report
    assert report["referential_integrity"]["referential_integrity_status"] == "VALID"
    assert "package_files" in report
    assert len(report["package_files"]) >= 10

    # 5. Verify Idempotent re-upload does not duplicate records
    dup_resp = await async_client.post(
        "/api/v1/ingestion/upload",
        files={"file": ("hospital_ehr_export_2000.zip", archive_bytes, "application/zip")},
        data={
            "source_system": "metropolitan_ehr",
            "idempotency_key": idempotency_key,
            "sync": "true",
        },
        headers={"X-API-Key": "dev-test-key"},
    )
    assert dup_resp.status_code in [200, 201]
    dup_data = dup_resp.json()
    assert dup_data["job_id"] == job_id
