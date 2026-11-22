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
