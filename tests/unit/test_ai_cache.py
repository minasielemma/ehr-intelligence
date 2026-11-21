"""Unit tests for deterministic FHIR Bundle canonicalization and SQLite cache management."""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import (
    SummaryCacheManager,
    canonicalize_fhir_bundle,
    generate_summary_cache_key,
)
from app.core.config import Settings
from app.models.database import get_session_factory, init_db
from app.models.ingestion import PatientModel
from app.models.summary import ClinicalSummaryModel
from app.schemas.summary import (
    ClinicalSummaryResponse,
    ConfidenceLevel,
    ConfidenceScore,
    DiagnosticRecordsSummary,
    ModelMetadata,
)


def test_canonicalize_fhir_bundle_order_independent():
    """Verify that bundle entry ordering does not affect canonical hash."""
    res_a = {"resourceType": "Observation", "id": "obs-1", "valueString": "Normal"}
    res_b = {"resourceType": "Condition", "id": "cond-1", "code": {"text": "Asthma"}}

    bundle1 = {
        "resourceType": "Bundle",
        "id": "bundle-001",
        "timestamp": "2026-11-20T10:00:00Z",
        "entry": [{"resource": res_a}, {"resource": res_b}],
    }

    # Different bundle id, different timestamp, reverse entry order
    bundle2 = {
        "resourceType": "Bundle",
        "id": "bundle-002",
        "timestamp": "2026-11-21T18:00:00Z",
        "entry": [{"resource": res_b}, {"resource": res_a}],
    }

    hash1 = canonicalize_fhir_bundle(bundle1)
    hash2 = canonicalize_fhir_bundle(bundle2)

    assert hash1 == hash2, "Identical clinical content in different entry order must produce matching hash"


def test_canonicalize_fhir_bundle_detects_changes():
    """Verify that changes to clinical resources alter the canonical hash."""
    bundle_orig = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Observation", "id": "obs-1", "valueQuantity": {"value": 10.0}}}
        ],
    }
    bundle_changed = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Observation", "id": "obs-1", "valueQuantity": {"value": 15.0}}}
        ],
    }

    assert canonicalize_fhir_bundle(bundle_orig) != canonicalize_fhir_bundle(bundle_changed)


def test_generate_summary_cache_key_components():
    """Verify that patient, bundle hash, prompt version, and model config uniquely determine cache key."""
    key1 = generate_summary_cache_key(
        patient_id="pat-1",
        bundle_hash="hash-abc",
        prompt_version="v1.0.0",
        provider="ollama",
        model="gemma3:12b",
        temperature=0.1,
    )

    # Identical arguments produce identical key
    key1_repeat = generate_summary_cache_key(
        patient_id="pat-1",
        bundle_hash="hash-abc",
        prompt_version="v1.0.0",
        provider="ollama",
        model="gemma3:12b",
        temperature=0.1,
    )
    assert key1 == key1_repeat

    # Different patient -> different key
    key_diff_patient = generate_summary_cache_key(
        patient_id="pat-2",
        bundle_hash="hash-abc",
        prompt_version="v1.0.0",
        provider="ollama",
        model="gemma3:12b",
        temperature=0.1,
    )
    assert key1 != key_diff_patient

    # Different prompt version -> different key (invalidates cache)
    key_diff_prompt = generate_summary_cache_key(
        patient_id="pat-1",
        bundle_hash="hash-abc",
        prompt_version="v1.1.0",
        provider="ollama",
        model="gemma3:12b",
        temperature=0.1,
    )
    assert key1 != key_diff_prompt

    # Different model -> different key
    key_diff_model = generate_summary_cache_key(
        patient_id="pat-1",
        bundle_hash="hash-abc",
        prompt_version="v1.0.0",
        provider="ollama",
        model="llama3.1:8b",
        temperature=0.1,
    )
    assert key1 != key_diff_model


@pytest.mark.asyncio
async def test_summary_cache_manager_crud_and_invalidation(tmp_path):
    """Verify SQLite cache storage, retrieval, and explicit invalidation."""
    db_file = str(tmp_path / "test_cache.db")
    await init_db(database_path=db_file)
    session_factory = get_session_factory(f"sqlite+aiosqlite:///{db_file}")

    test_settings = Settings(
        DATABASE_PATH=db_file,
        SUMMARY_CACHE_TTL_SECONDS=3600,
    )

    sample_summary = ClinicalSummaryResponse(
        patient_id="pat-cache-1",
        chief_concern="Routine exam",
        key_diagnoses=["Hypertension"],
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient is stable with controlled blood pressure.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="Well documented"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=["Patient/pat-cache-1"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )

    async with session_factory() as session:
        # Pre-create patient to satisfy foreign key constraint
        pat_model = PatientModel(
            id="pat-cache-1",
            source_system="test",
            mrn="MRN-CACHE-1",
            first_name="John",
            last_name="Doe",
        )
        session.add(pat_model)
        await session.commit()

    async with session_factory() as session:
        cache_manager = SummaryCacheManager(session, test_settings)
        cache_key = "test-cache-key-001"

        # 1. Cache Miss
        cached = await cache_manager.get_cached_summary(cache_key)
        assert cached is None

        # 2. Put in cache
        await cache_manager.put_cached_summary(
            cache_key=cache_key,
            patient_id="pat-cache-1",
            bundle_hash="b-hash-1",
            provider="ollama",
            model_name="gemma3:12b",
            summary=sample_summary,
        )
        await session.commit()

    async with session_factory() as session:
        cache_manager = SummaryCacheManager(session, test_settings)

        # 3. Cache Hit
        cached = await cache_manager.get_cached_summary("test-cache-key-001")
        assert cached is not None
        cached_summary, model = cached
        assert cached_summary.patient_id == "pat-cache-1"
        assert cached_summary.clinical_summary == sample_summary.clinical_summary
        assert model.cache_key == "test-cache-key-001"

        # 4. Explicit Invalidation
        deleted = await cache_manager.invalidate_patient_cache("pat-cache-1")
        assert deleted == 1
        await session.commit()

        # 5. Verify Purged
        assert await cache_manager.get_cached_summary("test-cache-key-001") is None


@pytest.mark.asyncio
async def test_cache_lock_pruning_prevents_memory_leak():
    """Verify that acquire_lock prunes entries from _CACHE_LOCKS after release."""
    from app.ai.cache import _CACHE_LOCKS, SummaryCacheManager

    test_key = "ephemeral-key-for-pruning-test"
    assert test_key not in _CACHE_LOCKS

    async with SummaryCacheManager.acquire_lock(test_key):
        # Inside the block, the lock must exist in the tracking map
        assert test_key in _CACHE_LOCKS

    # Once released, the key must be pruned to avoid memory leak
    assert test_key not in _CACHE_LOCKS

