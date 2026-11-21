"""End-to-end integration tests for FHIR R4 Normalization, Conformance Validation, and Storage Pipeline."""

import pytest
from httpx import AsyncClient

from app.models.database import get_session_factory
from app.repositories.fhir_bundle_repository import FHIRBundleRepository


@pytest.mark.asyncio
async def test_e2e_fhir_normalize_payload_endpoint(async_client: AsyncClient, test_settings):
    """Verify POST /api/v1/fhir/normalize directly normalizes Task 1 canonical representations."""
    payload = {
        "patient": {
            "id": "pat-pipeline-001",
            "source_system": "st_jude_ehr",
            "source_patient_id": "STJ-001",
            "mrn": "MRN-STJ-001",
            "first_name": "Alexander",
            "last_name": "Hamilton",
            "date_of_birth": "1980-01-11",
            "administrative_gender": "male",
            "contact_info": {"phone": "555-1776"},
        },
        "records": [
            {
                "id": "rec-note-001",
                "job_id": "job-init-001",
                "patient_id": "pat-pipeline-001",
                "record_type": "progress_note",
                "fingerprint": "sha256-fingerprint-note-001",
                "record_date": "2026-11-20T10:00:00Z",
                "cleaned_text": "Patient seen for annual wellness examination. Cardiopulmonary exam normal.",
            }
        ],
        "bundle_type": "collection",
        "save_to_store": True,
    }

    response = await async_client.post(
        "/api/v1/fhir/normalize",
        json=payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == 200, f"Normalization failed: {response.text}"
    data = response.json()

    assert data["success"] is True
    assert data["patient_mrn"] == "MRN-STJ-001"
    assert data["persisted"] is True
    bundle_id = data["bundle_id"]
    assert bundle_id is not None

    bundle = data["bundle"]
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert len(bundle["entry"]) == 2

    report = data["validation_report"]
    assert report["status"] in ["VALID", "WARNING"]
    assert report["error_count"] == 0

    # Retrieve stored bundle via GET endpoint
    get_resp = await async_client.get(
        f"/api/v1/fhir/bundles/{bundle_id}",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert get_resp.status_code == 200
    retrieved_bundle = get_resp.json()
    assert retrieved_bundle["id"] == bundle_id
    assert retrieved_bundle["entry"][0]["resource"]["resourceType"] == "Patient"

    # Retrieve validation report via GET endpoint
    rep_resp = await async_client.get(
        f"/api/v1/fhir/bundles/{bundle_id}/report",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert rep_resp.status_code == 200
    retrieved_report = rep_resp.json()
    assert retrieved_report["status"] in ["VALID", "WARNING"]


@pytest.mark.asyncio
async def test_gatekeeper_rejects_invalid_bundle_from_storage(async_client: AsyncClient, test_settings):
    """Verify invalid bundles are rejected by gatekeeper validation and NOT persisted to output store."""
    payload = {
        "patient": {
            "id": "pat-invalid-002",
            "source_system": "bad_hospital",
            "mrn": "MRN-BAD-002",
            "first_name": "Faulty",
            "last_name": "Record",
            "date_of_birth": "INVALID_DATE_FORMAT_123",  # Illegal birthDate
            "administrative_gender": "ILLEGAL_GENDER",
        },
        "bundle_type": "collection",
        "save_to_store": True,
    }

    response = await async_client.post(
        "/api/v1/fhir/normalize",
        json=payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is False
    assert data["persisted"] is False
    assert data["validation_report"]["status"] == "INVALID"
    assert data["validation_report"]["error_count"] >= 1

    # Ensure NOT persisted in database
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        bundle_repo = FHIRBundleRepository(session)
        bundles = await bundle_repo.get_by_patient_id("pat-invalid-002")
        assert len(bundles) == 0, "Gatekeeper rule violated: invalid bundle was persisted to database!"


@pytest.mark.asyncio
async def test_e2e_task1_ingested_patient_to_fhir_bundle(async_client: AsyncClient, test_settings):
    """Full lifecycle test: Ingest Task 1 data -> Reconcile Patient -> Normalize to FHIR R4 -> Retrieve."""
    # 1. Ingest clinical records via Task 1 JSON endpoint
    ingest_payload = {
        "source_system": "general_hospital",
        "idempotency_key": "idemp-fhir-pipeline-lifecycle-01",
        "records": [
            {
                "patient": {
                    "mrn": "MRN-GH-9988",
                    "first_name": "Thomas",
                    "last_name": "Edison",
                    "dob": "1947-02-11",
                    "gender": "male",
                },
                "document": {
                    "clinical_note": "Initial evaluation for hypertension. Started on ACE inhibitor.",
                    "record_type": "progress_note",
                },
                "metadata": {
                    "record_date": "2026-11-15T09:30:00Z",
                    "record_type": "progress_note",
                },
            }
        ],
    }

    ingest_resp = await async_client.post(
        "/api/v1/ingestion/json",
        json=ingest_payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert ingest_resp.status_code == 201
    job_id = ingest_resp.json()["job_id"]

    # Retrieve patient records created by the job
    records_resp = await async_client.get(
        f"/api/v1/ingestion/jobs/{job_id}/records",
        headers={"X-API-Key": "dev-test-key"},
    )
    records_data = records_resp.json()
    recs = records_data.get("items") or records_data.get("records") or []
    assert len(recs) == 1
    patient_id = recs[0]["patient_id"]
    assert patient_id is not None

    # 2. Normalize patient from database via POST /api/v1/fhir/normalize/patient/{patient_id}
    norm_resp = await async_client.post(
        f"/api/v1/fhir/normalize/patient/{patient_id}?bundle_type=collection&save_to_store=true",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert norm_resp.status_code == 200
    norm_data = norm_resp.json()

    assert norm_data["success"] is True
    assert norm_data["persisted"] is True
    bundle_id = norm_data["bundle_id"]

    bundle = norm_data["bundle"]
    assert bundle["resourceType"] == "Bundle"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][0]["resource"]["name"][0]["family"] == "Edison"

    # 3. Retrieve patient bundles list
    list_resp = await async_client.get(
        f"/api/v1/fhir/bundles/patient/{patient_id}",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert list_resp.status_code == 200
    summaries = list_resp.json()
    assert len(summaries) >= 1
    assert summaries[0]["bundle_id"] == bundle_id
    assert summaries[0]["status"] in ["VALID", "WARNING"]


@pytest.mark.asyncio
async def test_e2e_batch_job_fhir_normalization(async_client: AsyncClient, test_settings):
    """Verify POST /api/v1/fhir/normalize/job/{job_id} batch-normalizes multiple patients with isolation."""
    # Ingest 2 distinct patients
    ingest_payload = {
        "source_system": "multi_pat_hospital",
        "idempotency_key": "idemp-multi-pat-batch-02",
        "records": [
            {
                "patient": {
                    "mrn": "MRN-PAT-01",
                    "first_name": "Isaac",
                    "last_name": "Newton",
                    "dob": "1942-12-25",
                    "gender": "male",
                },
                "document": "Routine checkup note.",
            },
            {
                "patient": {
                    "mrn": "MRN-PAT-02",
                    "first_name": "Marie",
                    "last_name": "Curie",
                    "dob": "1967-11-07",
                    "gender": "female",
                },
                "document": "Follow-up laboratory review.",
            },
        ],
    }

    ingest_resp = await async_client.post(
        "/api/v1/ingestion/json",
        json=ingest_payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert ingest_resp.status_code == 201
    job_id = ingest_resp.json()["job_id"]

    # Batch normalize the job
    batch_resp = await async_client.post(
        f"/api/v1/fhir/normalize/job/{job_id}?bundle_type=collection&save_to_store=true",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert batch_resp.status_code == 200
    results = batch_resp.json()

    assert len(results) == 2
    for res in results:
        assert res["success"] is True
        assert res["persisted"] is True
        assert res["bundle"]["resourceType"] == "Bundle"


@pytest.mark.asyncio
async def test_e2e_list_stored_bundles_pagination(async_client: AsyncClient, test_settings):
    """Verify GET /api/v1/fhir/bundles returns structured pagination metadata."""
    resp = await async_client.get(
        "/api/v1/fhir/bundles?page=1&page_size=10",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "total_pages" in data
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_e2e_idempotent_renormalization(async_client: AsyncClient, test_settings):
    """Verify re-normalizing identical patient records returns existing bundle without version increment."""
    payload = {
        "patient": {
            "id": "pat-idemp-999",
            "source_system": "hospital_idemp",
            "mrn": "MRN-IDEMP-999",
            "first_name": "Alan",
            "last_name": "Turing",
            "date_of_birth": "1912-06-23",
            "administrative_gender": "male",
        },
        "records": [
            {
                "id": "rec-idemp-01",
                "job_id": "job-idemp-01",
                "patient_id": "pat-idemp-999",
                "record_type": "clinical_note",
                "fingerprint": "sha256-idemp-01",
                "record_date": "2026-11-20T10:00:00Z",
                "cleaned_text": "Cryptographic analysis and general wellness examination.",
            }
        ],
        "bundle_type": "collection",
        "save_to_store": True,
    }

    # First call
    resp1 = await async_client.post(
        "/api/v1/fhir/normalize",
        json=payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["success"] is True
    bundle_id_1 = data1["bundle_id"]
    ver_1 = data1["version"]

    # Second call with exact same content
    resp2 = await async_client.post(
        "/api/v1/fhir/normalize",
        json=payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["success"] is True
    assert data2["bundle_id"] == bundle_id_1
    assert data2["version"] == ver_1, "Version must not increment on identical content!"


@pytest.mark.asyncio
async def test_e2e_patient_with_observations_normalization(async_client: AsyncClient, test_settings):
    """Verify normalizing database patient with ObservationModel entities succeeds without regex errors."""
    from app.models.ingestion import IngestionJobModel, ObservationModel, PatientModel

    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        job = IngestionJobModel(
            id="job-obs-e2e",
            source_system="hospital_labs",
            source_format="json",
            status="COMPLETED",
        )
        pat = PatientModel(
            id="pat-obs-e2e-01",
            source_system="hospital_labs",
            mrn="MRN-OBS-E2E",
            first_name="Rosalind",
            last_name="Franklin",
            administrative_gender="female",
            date_of_birth="1920-07-25",
        )
        obs1 = ObservationModel(
            id="obs-e2e-hr",
            patient_id="pat-obs-e2e-01",
            source_system="hospital_labs",
            job_id="job-obs-e2e",
            code="8867-4",
            display="Heart rate",
            value_numeric=76.0,
            unit="bpm",
        )
        obs2 = ObservationModel(
            id="obs-e2e-txt",
            patient_id="pat-obs-e2e-01",
            source_system="hospital_labs",
            job_id="job-obs-e2e",
            code="XRAY-01",
            display="Radiology impression",
            value_string="Crystalline structure verified. No abnormalities.",
        )
        session.add(job)
        session.add(pat)
        session.add(obs1)
        session.add(obs2)
        await session.commit()

    # Normalize from database via POST /api/v1/fhir/normalize/patient/{patient_id}
    resp = await async_client.post(
        "/api/v1/fhir/normalize/patient/pat-obs-e2e-01?bundle_type=collection&save_to_store=true",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True, f"Normalization failed: {data['validation_report']}"
    assert data["persisted"] is True
    assert data["validation_report"]["status"] in ["VALID", "WARNING"]
    assert data["validation_report"]["error_count"] == 0
