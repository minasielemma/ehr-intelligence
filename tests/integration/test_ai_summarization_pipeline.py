"""End-to-end integration tests for AI Clinical Summarization Pipeline, Caching, and REST Endpoints."""

import time
from httpx import AsyncClient
import pytest

from app.core.config import Settings
from app.models.database import get_session_factory
from app.models.ingestion import PatientModel
from app.repositories.fhir_bundle_repository import FHIRBundleRepository


@pytest.fixture
def sample_fhir_bundle():
    """Valid patient-centric FHIR R4 collection bundle."""
    return {
        "resourceType": "Bundle",
        "id": "bundle-integration-001",
        "type": "collection",
        "entry": [
            {
                "fullUrl": "http://hospital.smarthealth.org/fhir/Patient/pat-integ-1",
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-integ-1",
                    "identifier": [{"system": "http://hospital.org/mrn", "value": "MRN-INT-001"}],
                    "name": [{"family": "Mercer", "given": ["Aaron"]}],
                    "gender": "male",
                    "birthDate": "1975-03-22",
                },
            },
            {
                "fullUrl": "http://hospital.smarthealth.org/fhir/Encounter/enc-integ-1",
                "resource": {
                    "resourceType": "Encounter",
                    "id": "enc-integ-1",
                    "status": "finished",
                    "class": {"code": "AMB", "display": "Ambulatory"},
                    "subject": {"reference": "Patient/pat-integ-1"},
                    "period": {"start": "2026-11-18T09:00:00Z", "end": "2026-11-18T10:00:00Z"},
                    "reasonCode": [{"text": "Follow-up of Essential Hypertension"}],
                },
            },
            {
                "fullUrl": "http://hospital.smarthealth.org/fhir/Condition/cond-integ-1",
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-integ-1",
                    "subject": {"reference": "Patient/pat-integ-1"},
                    "code": {"text": "Essential Hypertension"},
                    "clinicalStatus": {"coding": [{"code": "active"}]},
                    "verificationStatus": {"coding": [{"code": "confirmed"}]},
                },
            },
            {
                "fullUrl": "http://hospital.smarthealth.org/fhir/Observation/obs-integ-bp",
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-integ-bp",
                    "status": "final",
                    "category": [{"coding": [{"code": "vital-signs"}]}],
                    "code": {"text": "Blood Pressure"},
                    "subject": {"reference": "Patient/pat-integ-1"},
                    "valueString": "136/84 mmHg",
                    "effectiveDateTime": "2026-11-18T09:15:00Z",
                },
            },
            {
                "fullUrl": "http://hospital.smarthealth.org/fhir/Observation/obs-integ-k",
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-integ-k",
                    "status": "final",
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "code": {"text": "Serum Potassium"},
                    "subject": {"reference": "Patient/pat-integ-1"},
                    "valueQuantity": {"value": 4.4, "unit": "mmol/L"},
                    "referenceRange": [{"low": {"value": 3.5}, "high": {"value": 5.0}}],
                    "interpretation": [{"coding": [{"code": "N"}]}],
                    "effectiveDateTime": "2026-11-18T09:30:00Z",
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_e2e_summarize_bundle_endpoint_and_caching(
    async_client: AsyncClient, sample_fhir_bundle
):
    """Verify POST /api/v1/ai/summarize/bundle, strict schema validation, and intelligent caching."""
    # Step 1: Initial call (Cache Miss)
    t0 = time.perf_counter()
    resp1 = await async_client.post(
        "/api/v1/ai/summarize/bundle",
        json={"bundle": sample_fhir_bundle, "force_refresh": False},
        headers={"X-API-Key": "dev-test-key"},
    )
    lat1 = (time.perf_counter() - t0) * 1000
    assert resp1.status_code == 200, f"Failed: {resp1.text}"
    data1 = resp1.json()

    assert data1["patient_id"] == "pat-integ-1"
    assert "clinical_summary" in data1
    assert data1["confidence"]["level"] in ["high", "moderate", "low"]
    assert data1["disclaimer"] == "AI-generated summary. Not a clinical diagnosis or medical decision."
    assert "Patient/pat-integ-1" in data1["source_references"]
    word_count = len(data1["clinical_summary"].split())
    assert word_count < 200

    # Step 2: Second call with identical payload (Cache HIT)
    t1 = time.perf_counter()
    resp2 = await async_client.post(
        "/api/v1/ai/summarize/bundle",
        json={"bundle": sample_fhir_bundle, "force_refresh": False},
        headers={"X-API-Key": "dev-test-key"},
    )
    lat2 = (time.perf_counter() - t1) * 1000
    assert resp2.status_code == 200
    data2 = resp2.json()

    # Data must match exactly
    assert data2["patient_id"] == data1["patient_id"]
    assert data2["clinical_summary"] == data1["clinical_summary"]
    # Cache hit must be fast
    assert lat2 < 100, f"Expected cache hit under 100ms, took {lat2:.1f}ms"

    # Step 3: Call with modified bundle (Cache MISS)
    modified_bundle = dict(sample_fhir_bundle)
    # Add a new observation
    modified_bundle["entry"] = list(sample_fhir_bundle["entry"]) + [
        {
            "resource": {
                "resourceType": "Observation",
                "id": "obs-integ-glu",
                "code": {"text": "Blood Glucose"},
                "valueQuantity": {"value": 110.0, "unit": "mg/dL"},
                "subject": {"reference": "Patient/pat-integ-1"},
            }
        }
    ]

    resp3 = await async_client.post(
        "/api/v1/ai/summarize/bundle",
        json={"bundle": modified_bundle, "force_refresh": False},
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["patient_id"] == "pat-integ-1"


@pytest.mark.asyncio
async def test_e2e_summarize_stored_patient_and_crud(
    async_client: AsyncClient, sample_fhir_bundle, test_settings
):
    """Verify summarization from stored DB bundle, GET summary, and DELETE cache endpoints."""
    # 1. Pre-populate patient and normalized bundle in database
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-stored-01",
            source_system="ehr_main",
            mrn="MRN-STORED-01",
            first_name="Eleanor",
            last_name="Vance",
        )
        session.add(pat)

        bundle_copy = dict(sample_fhir_bundle)
        bundle_copy["entry"][0]["resource"]["id"] = "pat-stored-01"

        b_repo = FHIRBundleRepository(session)
        await b_repo.save_bundle(
            bundle_id="bundle-stored-01",
            patient_id="pat-stored-01",
            patient_mrn="MRN-STORED-01",
            bundle_type="collection",
            bundle_json=bundle_copy,
            status="VALID",
        )
        await session.commit()

    # 2. Trigger summary generation for stored patient
    resp = await async_client.post(
        "/api/v1/ai/summarize/patient/pat-stored-01",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp.status_code == 200, f"Error: {resp.text}"
    summary_data = resp.json()
    assert summary_data["patient_id"] == "pat-stored-01"

    # 3. Retrieve stored summary via GET /api/v1/ai/summary/{patient_id}
    get_resp = await async_client.get(
        "/api/v1/ai/summary/pat-stored-01",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["patient_id"] == "pat-stored-01"

    # 4. Invalidate cache via DELETE /api/v1/ai/cache/{patient_id}
    del_resp = await async_client.delete(
        "/api/v1/ai/cache/pat-stored-01",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["invalidated"] is True
    assert del_data["deleted_records"] >= 1


@pytest.mark.asyncio
async def test_e2e_batch_summarization_with_error_isolation(
    async_client: AsyncClient, sample_fhir_bundle, test_settings
):
    """Verify batch summarization continues across valid and invalid patients without interruption."""
    # 1. Create one valid patient with a stored bundle
    session_factory = get_session_factory(test_settings.sqlite_url)
    async with session_factory() as session:
        pat = PatientModel(
            id="pat-batch-valid",
            source_system="ehr_main",
            mrn="MRN-BATCH-VAL",
            first_name="Valid",
            last_name="Patient",
        )
        session.add(pat)

        bundle_copy = dict(sample_fhir_bundle)
        bundle_copy["entry"][0]["resource"]["id"] = "pat-batch-valid"

        b_repo = FHIRBundleRepository(session)
        await b_repo.save_bundle(
            bundle_id="bundle-batch-val",
            patient_id="pat-batch-valid",
            patient_mrn="MRN-BATCH-VAL",
            bundle_type="collection",
            bundle_json=bundle_copy,
            status="VALID",
        )
        await session.commit()

    # 2. Request batch for one valid patient and one non-existent patient
    batch_payload = {
        "patient_ids": ["pat-batch-valid", "pat-non-existent-999"],
        "force_refresh": False,
    }

    resp = await async_client.post(
        "/api/v1/ai/summarize/batch",
        json=batch_payload,
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_patients"] == 2
    assert data["successful_count"] == 1
    assert data["failed_count"] == 1

    results = {r["patient_id"]: r for r in data["results"]}
    assert results["pat-batch-valid"]["status"] in ["SUCCESS", "CACHE_HIT"]
    assert results["pat-batch-valid"]["summary"] is not None
    assert results["pat-non-existent-999"]["status"] == "FAILED"
    assert "not found" in results["pat-non-existent-999"]["error_message"].lower()


@pytest.mark.asyncio
async def test_e2e_llm_provider_health_check(async_client: AsyncClient):
    """Verify GET /api/v1/ai/health endpoint returns provider diagnostics."""
    resp = await async_client.get(
        "/api/v1/ai/health",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "provider" in data
    assert "model" in data
    assert "available" in data


@pytest.mark.asyncio
async def test_e2e_provider_switching_configuration(test_settings, tmp_path, sample_fhir_bundle):
    """Verify switching LLM_PROVIDER from mock to ollama via settings without code changes."""
    db_file = str(tmp_path / "test_switching.db")
    session_factory = get_session_factory(f"sqlite+aiosqlite:///{db_file}")

    # Switch settings to ollama
    ollama_settings = Settings(
        DATABASE_PATH=db_file,
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://172.25.0.1:11434",
        OLLAMA_MODEL="artifish/llama3.2-uncensored:latest",
    )

    from app.ai.providers.factory import get_llm_provider
    provider = get_llm_provider(ollama_settings)
    assert provider.provider_name == "ollama"
    assert provider.model_name == "artifish/llama3.2-uncensored:latest"


@pytest.mark.asyncio
async def test_live_ollama_end_to_end_summarization(sample_fhir_bundle, tmp_path):
    """Verify live end-to-end Ollama inference when local Ollama service is reachable."""
    from app.ai.providers.ollama_provider import OllamaProvider
    from app.services.clinical_summarization_service import ClinicalSummarizationService
    from app.models.database import init_db

    db_file = str(tmp_path / "test_live_ollama.db")
    await init_db(database_path=db_file)
    session_factory = get_session_factory(f"sqlite+aiosqlite:///{db_file}")

    live_settings = Settings(
        DATABASE_PATH=db_file,
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://172.25.0.1:11434",
        OLLAMA_MODEL="artifish/llama3.2-uncensored:latest",
        LLM_TIMEOUT=120,
    )

    provider = OllamaProvider(
        settings=live_settings,
        base_url="http://172.25.0.1:11434",
        model="artifish/llama3.2-uncensored:latest",
    )

    # Check health first
    health = await provider.check_health()
    if not health.get("available"):
        pytest.skip(f"Ollama server or model not available for live test: {health}")

    async with session_factory() as session:
        service = ClinicalSummarizationService(
            session=session,
            settings=live_settings,
            provider=provider,
        )

        summary, was_cached, lat_ms = await service.summarize_bundle(
            bundle_data=sample_fhir_bundle,
            force_refresh=True,
        )

        assert summary.patient_id == "pat-integ-1"
        assert was_cached is False
        assert summary.word_count < 200
        assert summary.confidence.level.value in ["high", "moderate", "low"]
        assert summary.model_metadata.provider == "ollama"
        assert summary.model_metadata.model == "artifish/llama3.2-uncensored:latest"
        assert "Patient/pat-integ-1" in summary.source_references
        print(f"\nLive Ollama Inference Success ({lat_ms:.1f}ms): {summary.clinical_summary}")
