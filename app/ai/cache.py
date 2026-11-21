"""Intelligent persistent caching, bundle canonicalization, and concurrency locking for clinical summaries."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.summary import ClinicalSummaryModel
from app.repositories.clinical_summary_repository import ClinicalSummaryRepository
from app.schemas.summary import ClinicalSummaryResponse

logger = get_logger(__name__)

_CACHE_LOCKS: Dict[str, List[Any]] = {}  # cache_key -> [asyncio.Lock, ref_count]
_LOCK_MANAGER = asyncio.Lock()


def canonicalize_fhir_bundle(bundle_data: Dict[str, Any]) -> str:
    """Deterministically canonicalize a FHIR Bundle payload and compute SHA-256 content hash.

    Strips volatile envelope headers (id, timestamp) and sorts bundle entries deterministically
    by resourceType and id so identical clinical content produces an identical hash regardless of ordering.
    """
    if not isinstance(bundle_data, dict):
        serialized = json.dumps(bundle_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    # Clone and strip volatile root fields
    clean_bundle: Dict[str, Any] = {
        k: v for k, v in bundle_data.items() if k not in ("id", "timestamp")
    }

    # If entries exist, sort entries deterministically by resourceType and id
    entries = clean_bundle.get("entry")
    if isinstance(entries, list):
        sorted_entries = []
        for e in entries:
            if isinstance(e, dict) and "resource" in e and isinstance(e["resource"], dict):
                r = e["resource"]
                key = (r.get("resourceType", ""), str(r.get("id", "")))
                sorted_entries.append((key, e))
            else:
                sorted_entries.append((("", ""), e))
        
        sorted_entries.sort(key=lambda item: item[0])
        clean_bundle["entry"] = [item[1] for item in sorted_entries]

    serialized = json.dumps(clean_bundle, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def generate_summary_cache_key(
    patient_id: str,
    bundle_hash: str,
    prompt_version: str,
    provider: str,
    model: str,
    temperature: float = 0.1,
) -> str:
    """Generate deterministic SHA-256 cache key.

    Formula: SHA256(patient_id + canonicalized_bundle_hash + prompt_version + model_configuration)
    """
    model_config = f"{provider.lower()}:{model}:{temperature:.2f}"
    composite = f"{patient_id}|{bundle_hash}|{prompt_version}|{model_config}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


class SummaryCacheManager:
    """Coordinates persistent SQLite summary caching, cache invalidation, and concurrent execution locks."""

    def __init__(self, session: AsyncSession, settings: Optional[Settings] = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = ClinicalSummaryRepository(session)

    @classmethod
    @asynccontextmanager
    async def acquire_lock(cls, cache_key: str):
        """Acquire an asyncio.Lock for a cache key with automatic memory pruning upon release."""
        async with _LOCK_MANAGER:
            if cache_key not in _CACHE_LOCKS:
                _CACHE_LOCKS[cache_key] = [asyncio.Lock(), 0]
            _CACHE_LOCKS[cache_key][1] += 1
            lock = _CACHE_LOCKS[cache_key][0]

        try:
            async with lock:
                yield lock
        finally:
            async with _LOCK_MANAGER:
                if cache_key in _CACHE_LOCKS:
                    _CACHE_LOCKS[cache_key][1] -= 1
                    if _CACHE_LOCKS[cache_key][1] <= 0:
                        del _CACHE_LOCKS[cache_key]

    @classmethod
    async def get_lock_for_key(cls, cache_key: str) -> asyncio.Lock:
        """Retrieve or create an asyncio.Lock for a specific cache key."""
        async with _LOCK_MANAGER:
            if cache_key not in _CACHE_LOCKS:
                _CACHE_LOCKS[cache_key] = [asyncio.Lock(), 1]
            return _CACHE_LOCKS[cache_key][0]

    async def get_cached_summary(
        self,
        cache_key: str,
    ) -> Optional[Tuple[ClinicalSummaryResponse, ClinicalSummaryModel]]:
        """Look up active summary in cache, evaluating TTL expiration if configured."""
        model = await self.repository.get_by_cache_key(cache_key)
        if not model:
            return None

        # Check TTL expiration if configured
        ttl = self.settings.SUMMARY_CACHE_TTL_SECONDS
        if ttl is not None and ttl > 0:
            now_dt = datetime.now(timezone.utc)
            # Support naive/aware timestamps
            created = model.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_seconds = (now_dt - created).total_seconds()
            if age_seconds > ttl:
                logger.info(
                    "Cached summary [%s] for key [%s] expired (age: %.1fs > ttl: %ds)",
                    model.id,
                    cache_key[:12],
                    age_seconds,
                    ttl,
                )
                await self.repository.delete_by_cache_key(cache_key)
                return None

        try:
            summary = ClinicalSummaryResponse.model_validate(model.summary_json)
            return summary, model
        except Exception as exc:
            logger.warning("Cached summary [%s] corrupted or invalid schema: %s", model.id, exc)
            return None

    async def put_cached_summary(
        self,
        cache_key: str,
        patient_id: str,
        bundle_hash: str,
        provider: str,
        model_name: str,
        summary: ClinicalSummaryResponse,
        bundle_id: Optional[str] = None,
        prompt_version: str = "v1.0.0",
        temperature: float = 0.1,
        status: str = "COMPLETED",
        execution_time_ms: float = 0.0,
        file_path: Optional[str] = None,
    ) -> ClinicalSummaryModel:
        """Persist generated summary to cache."""
        summary_dict = summary.model_dump()
        model, _ = await self.repository.save_summary(
            cache_key=cache_key,
            patient_id=patient_id,
            bundle_id=bundle_id,
            bundle_hash=bundle_hash,
            provider=provider,
            model_name=model_name,
            prompt_version=prompt_version,
            temperature=temperature,
            status=status,
            summary_json=summary_dict,
            clinical_summary_text=summary.clinical_summary,
            word_count=summary.word_count,
            confidence_level=summary.confidence.level.value,
            execution_time_ms=execution_time_ms,
            file_path=file_path,
        )
        return model

    async def invalidate_patient_cache(self, patient_id: str) -> int:
        """Purge all cached summaries for a patient."""
        return await self.repository.delete_by_patient_id(patient_id)
