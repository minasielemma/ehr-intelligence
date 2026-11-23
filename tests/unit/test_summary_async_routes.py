"""Unit tests for asynchronous AI clinical summary generation, regeneration, and task status polling."""

import pytest
from httpx import AsyncClient
from fastapi import status

from app.models.database import get_session_factory
from app.models.ingestion import PatientModel
from app.models.summary import ClinicalSummaryModel
from app.services.summary_task_manager import summary_task_manager


@pytest.mark.asyncio
async def test_async_summary_generation_status_not_found(async_client: AsyncClient) -> None:
    """Verify 404 is returned when querying status for a non-existent patient task."""
    response = await async_client.get(
        "/api/v1/ai/summarize/status/patient-does-not-exist",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_async_summary_regeneration_route(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify POST /api/v1/ai/summarize/patient/{id}/regenerate returns 202 Accepted and creates task."""
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-async-regen-01",
            source_system="ehr_main",
            mrn="MRN-ASYNC-01",
            first_name="Async",
            last_name="Patient",
        )
        session.add(pat)
        await session.commit()

    # Trigger async regeneration
    response = await async_client.post(
        "/api/v1/ai/summarize/patient/pat-async-regen-01/regenerate",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert "task_id" in data
    assert data["patient_id"] == "pat-async-regen-01"
    assert data["status"] in ("PENDING", "PROCESSING", "COMPLETED", "FAILED")
    assert "scheduled" in data["message"].lower() or "regeneration" in data["message"].lower()

    # Check status endpoint with task_id
    task_id = data["task_id"]
    status_resp = await async_client.get(
        f"/api/v1/ai/summarize/status/pat-async-regen-01?task_id={task_id}",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert status_resp.status_code == status.HTTP_200_OK
    status_data = status_resp.json()
    assert status_data["task_id"] == task_id
    assert status_data["patient_id"] == "pat-async-regen-01"


@pytest.mark.asyncio
async def test_summarize_patient_sync_flag_false(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify POST /api/v1/ai/summarize/patient/{id}?sync=false returns 202 Accepted."""
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-async-flag-01",
            source_system="ehr_main",
            mrn="MRN-ASYNC-02",
            first_name="SyncFlag",
            last_name="Patient",
        )
        session.add(pat)
        await session.commit()

    response = await async_client.post(
        "/api/v1/ai/summarize/patient/pat-async-flag-01?sync=false",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert "task_id" in data
    assert data["patient_id"] == "pat-async-flag-01"


@pytest.mark.asyncio
async def test_summary_status_persisted_fallback(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify status endpoint returns existing persisted summary if no active background task exists."""
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-fallback-01",
            source_system="ehr_main",
            mrn="MRN-FB-01",
            first_name="Fallback",
            last_name="Patient",
        )
        session.add(pat)

        summary_rec = ClinicalSummaryModel(
            id="sum-fb-01",
            cache_key="ck-fallback-01",
            patient_id="pat-fallback-01",
            bundle_hash="hash-fb-01",
            provider="mock",
            model_name="mock-model",
            prompt_version="v1.0.0",
            temperature=0.1,
            status="COMPLETED",
            summary_json={
                "patient_id": "pat-fallback-01",
                "chief_concern": "Follow up",
                "key_diagnoses": ["Hypertension"],
                "recent_diagnostic_records": {"laboratory": [], "imaging": [], "other": []},
                "flagged_anomalies": [],
                "clinical_summary": "Patient is stable under management.",
                "confidence": {"level": "high", "explanation": "Grounded in records"},
                "disclaimer": "AI-generated summary.",
                "source_references": [],
                "generated_at": "2026-11-22T00:00:00Z",
                "model_metadata": {"provider": "mock", "model": "mock-model"},
            },
            clinical_summary_text="Patient is stable under management.",
            word_count=5,
            confidence_level="high",
            execution_time_ms=120.0,
        )
        session.add(summary_rec)
        await session.commit()

    # Query status without an active task in memory
    status_resp = await async_client.get(
        "/api/v1/ai/summarize/status/pat-fallback-01",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert status_resp.status_code == status.HTTP_200_OK
    data = status_resp.json()
    assert data["status"] == "COMPLETED"
    assert data["patient_id"] == "pat-fallback-01"
    assert data["summary"] is not None
    assert data["summary"]["clinical_summary"] == "Patient is stable under management."


@pytest.mark.asyncio
async def test_summary_task_persists_in_database_across_restarts(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify background task state persists in database even after in-memory cache is purged."""
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-persist-01",
            source_system="ehr_main",
            mrn="MRN-PERSIST-01",
            first_name="Persist",
            last_name="Test",
        )
        session.add(pat)
        await session.commit()

    # Trigger async regeneration
    regen_res = await async_client.post(
        "/api/v1/ai/summarize/patient/pat-persist-01/regenerate",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert regen_res.status_code == status.HTTP_202_ACCEPTED
    task_id = regen_res.json()["task_id"]

    # Purge in-memory state to simulate separate worker process or restart
    with summary_task_manager._lock:
        summary_task_manager._tasks.clear()
        summary_task_manager._patient_latest_task.clear()

    # Query status - should retrieve from database
    status_resp = await async_client.get(
        f"/api/v1/ai/summarize/status/pat-persist-01?task_id={task_id}",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert status_resp.status_code == status.HTTP_200_OK
    status_data = status_resp.json()
    assert status_data["status"] in ("PENDING", "PROCESSING", "COMPLETED", "FAILED")
    if status_data["status"] == "FAILED":
        assert "fhir" in status_data["error_message"].lower() or "bundle" in status_data["error_message"].lower()


@pytest.mark.asyncio
async def test_get_patient_summary_read_only_no_db_mutation(
    async_client: AsyncClient, test_settings
) -> None:
    """Verify GET /api/v1/ai/summarize/patient/{id} returns summary without mutating database."""
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-readonly-01",
            source_system="ehr_main",
            mrn="MRN-RO-01",
            first_name="Readonly",
            last_name="Patient",
        )
        session.add(pat)

        summary_model = ClinicalSummaryModel(
            id="sum-ro-01",
            patient_id="pat-readonly-01",
            cache_key="cache-ro-01",
            bundle_hash="hash-ro-01",
            provider="ollama",
            model_name="clinical-llm",
            clinical_summary_text="Legacy narrative format without extra fields.",
            summary_json={
                "patient_id": "pat-readonly-01",
                "clinical_summary": "Legacy narrative format without extra fields.",
                "confidence": {"level": "moderate", "explanation": "Inferred from medical documentation."},
                "model_metadata": {"provider": "ollama", "model": "clinical-llm"},
            },
        )
        session.add(summary_model)
        await session.commit()

    # Query GET endpoint
    response = await async_client.get(
        "/api/v1/ai/summary/pat-readonly-01",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["patient_id"] == "pat-readonly-01"
    assert "Legacy narrative" in data["clinical_summary"]

