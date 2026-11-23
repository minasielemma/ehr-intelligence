"""Unit tests for patient directory, detail inspection, and linked FHIR resource endpoints."""

import pytest
from httpx import AsyncClient
from fastapi import status


@pytest.mark.asyncio
async def test_patients_list_empty(async_client: AsyncClient) -> None:
    """Verify /api/v1/patients handles empty database gracefully."""
    response = await async_client.get(
        "/api/v1/patients",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_patients_workflow(async_client: AsyncClient) -> None:
    """Verify ingesting a patient allows querying them via /api/v1/patients and /api/v1/patients/{id}."""
    # 1. Ingest sample patient
    payload = {
        "source_system": "metro_health",
        "records": [
            {
                "patient_id": "P-TEST-001",
                "mrn": "MRN-TEST-001",
                "first_name": "Eleanor",
                "last_name": "Vance",
                "dob": "1980-05-12",
                "gender": "female",
                "record_type": "note",
                "clinical_text": "Patient with mild asthma presenting for annual checkup.",
            }
        ],
    }
    ingest_res = await async_client.post(
        "/api/v1/ingestion/json",
        json=payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert ingest_res.status_code == status.HTTP_201_CREATED

    # 2. Query patients list
    pats_res = await async_client.get(
        "/api/v1/patients?query=Eleanor",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert pats_res.status_code == status.HTTP_200_OK
    pats_data = pats_res.json()
    assert pats_data["total"] >= 1
    found = pats_data["items"][0]
    assert found["first_name"] == "Eleanor"
    assert found["last_name"] == "Vance"
    patient_uuid = found["id"]

    # 3. Query patient detail
    detail_res = await async_client.get(
        f"/api/v1/patients/{patient_uuid}",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert detail_res.status_code == status.HTTP_200_OK
    detail_data = detail_res.json()
    assert detail_data["first_name"] == "Eleanor"
    assert "domain_counts" in detail_data

    # 4. Query linked FHIR resources
    res_res = await async_client.get(
        f"/api/v1/patients/{patient_uuid}/fhir-resources",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert res_res.status_code == status.HTTP_200_OK
    assert isinstance(res_res.json(), list)

    # 5. Query jobs list
    jobs_res = await async_client.get(
        "/api/v1/ingestion/jobs",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert jobs_res.status_code == status.HTTP_200_OK
    jobs_data = jobs_res.json()
    assert jobs_data["total"] >= 1


@pytest.mark.asyncio
async def test_patient_fhir_resources_unbundled_fallback(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify GET /api/v1/patients/{id}/fhir-resources gracefully falls back to domain models when no bundle exists."""
    from app.models.database import get_session_factory
    from app.models.ingestion import PatientModel, ObservationModel, ConditionModel, DiagnosticReportModel, IngestionJobModel

    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        job = IngestionJobModel(id="job-unbundled-1", source_system="ehr", source_format="csv")
        session.add(job)
        pat = PatientModel(id="pat-unbundled-1", source_system="ehr", mrn="MRN-UNB-1", first_name="Unb", last_name="Test")
        session.add(pat)

        obs = ObservationModel(
            id="obs-unb-1",
            job_id="job-unbundled-1",
            source_system="ehr",
            patient_id="pat-unbundled-1",
            code="8480-6",
            display="Systolic blood pressure",
            value_numeric=120.0,
            unit="mmHg",
            effective_date="2026-01-01",
        )
        session.add(obs)

        cond = ConditionModel(
            id="cond-unb-1",
            job_id="job-unbundled-1",
            source_system="ehr",
            patient_id="pat-unbundled-1",
            code="I10",
            display="Essential hypertension",
            clinical_status="active",
            verification_status="confirmed",
        )
        session.add(cond)

        diag = DiagnosticReportModel(
            id="diag-unb-1",
            job_id="job-unbundled-1",
            source_system="ehr",
            patient_id="pat-unbundled-1",
            code="CBC",
            display="Complete Blood Count",
            conclusion="Normal",
        )
        session.add(diag)
        await session.commit()

    resp = await async_client.get(
        "/api/v1/patients/pat-unbundled-1/fhir-resources",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()
    assert len(items) == 3
    types = {item["resource_type"] for item in items}
    assert types == {"Observation", "Condition", "DiagnosticReport"}


@pytest.mark.asyncio
async def test_patient_fhir_resources_by_mrn_and_normalization(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify GET /api/v1/patients/{mrn}/fhir-resources resolves by MRN and matches UUID query."""
    from app.models.database import get_session_factory
    from app.models.ingestion import PatientModel, ObservationModel, IngestionJobModel

    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        job = IngestionJobModel(id="job-mrn-test", source_system="ehr", source_format="csv")
        session.add(job)
        pat = PatientModel(id="pat-mrn-uuid-1", source_system="ehr", mrn="MRN-TARGET-99", first_name="Target", last_name="Patient")
        session.add(pat)

        obs = ObservationModel(
            id="obs-mrn-1",
            job_id="job-mrn-test",
            source_system="ehr",
            patient_id="pat-mrn-uuid-1",
            code="8480-6",
            display="Systolic blood pressure",
            value_numeric=125.0,
            unit="mmHg",
            effective_date="2026-02-01",
        )
        session.add(obs)
        await session.commit()

    # Query by UUID
    resp_uuid = await async_client.get(
        "/api/v1/patients/pat-mrn-uuid-1/fhir-resources",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp_uuid.status_code == status.HTTP_200_OK
    items_uuid = resp_uuid.json()
    assert len(items_uuid) >= 1

    # Query by MRN
    resp_mrn = await async_client.get(
        "/api/v1/patients/MRN-TARGET-99/fhir-resources",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp_mrn.status_code == status.HTTP_200_OK
    items_mrn = resp_mrn.json()
    assert len(items_mrn) == len(items_uuid)
    assert items_mrn[0]["id"] == items_uuid[0]["id"]

    # Normalize by MRN
    norm_resp = await async_client.post(
        "/api/v1/fhir/normalize/patient/MRN-TARGET-99?bundle_type=collection&save_to_store=true",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert norm_resp.status_code == status.HTTP_200_OK
    norm_data = norm_resp.json()
    assert norm_data["patient_id"] == "pat-mrn-uuid-1"
    assert norm_data["patient_mrn"] == "MRN-TARGET-99"


