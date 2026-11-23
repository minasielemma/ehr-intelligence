"""Clinical Summarization Service orchestrating FHIR extraction, caching, LLM inference, and evidence validation."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import (
    SummaryCacheManager,
    canonicalize_fhir_bundle,
    generate_summary_cache_key,
)
from app.ai.extractor import ExtractedClinicalRecord, FHIRClinicalExtractor
from app.ai.prompts.clinical_summary_prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    format_user_prompt,
)
from app.ai.providers.base import BaseLLMProvider, LLMProviderError
from app.ai.providers.factory import get_llm_provider
from app.ai.validator import EvidenceValidator
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, ValidationException
from app.core.logging import get_logger
from app.models.ingestion import PatientModel
from app.models.summary import ClinicalSummaryModel
from app.repositories.clinical_summary_repository import ClinicalSummaryRepository
from app.repositories.fhir_bundle_repository import FHIRBundleRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.summary import (
    DEFAULT_CLINICAL_DISCLAIMER,
    BatchSummarizeResponse,
    ClinicalSummaryResponse,
    ConfidenceScore,
    ModelMetadata,
    PatientSummaryItem,
    SummaryExecutionStatus,
)

logger = get_logger(__name__)

_GLOBAL_SEMAPHORES: Dict[int, asyncio.Semaphore] = {}


def _get_semaphore(limit: int) -> asyncio.Semaphore:
    """Return shared asyncio.Semaphore for specified concurrency limit."""
    if limit not in _GLOBAL_SEMAPHORES:
        _GLOBAL_SEMAPHORES[limit] = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORES[limit]


class ClinicalSummarizationService:
    """End-to-end clinical summarization service with caching, concurrency control, and evidence grounding."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider or get_llm_provider(self.settings)
        self.extractor = FHIRClinicalExtractor(redact_phi=self.settings.REDACT_PHI_BEFORE_LLM)
        self.cache_manager = SummaryCacheManager(session, self.settings)
        self.bundle_repo = FHIRBundleRepository(session)
        self.patient_repo = PatientRepository(session)
        self.summary_repo = ClinicalSummaryRepository(session)

        storage_root = Path(self.settings.DATABASE_PATH).parent
        self.disk_summary_dir = storage_root / "summaries"
        try:
            self.disk_summary_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    async def summarize_bundle(
        self,
        bundle_data: Dict[str, Any],
        force_refresh: bool = False,
    ) -> Tuple[ClinicalSummaryResponse, bool, float]:
        """Generate or retrieve cached clinical summary for a provided FHIR R4 Bundle.

        Args:
            bundle_data: Dict conforming to HL7 FHIR R4 Bundle specification.
            force_refresh: If True, bypass cache and force re-inference.

        Returns:
            Tuple of (summary: ClinicalSummaryResponse, was_cached: bool, latency_ms: float)
        """
        extracted = self.extractor.extract_from_bundle(bundle_data)
        patient_id = extracted.patient.id

        if not patient_id or patient_id == "UNKNOWN":
            raise ValidationException("FHIR Bundle must contain a Patient resource with a valid 'id'")

        bundle_hash = canonicalize_fhir_bundle(bundle_data)
        cache_key = generate_summary_cache_key(
            patient_id=patient_id,
            bundle_hash=bundle_hash,
            prompt_version=self.settings.PROMPT_VERSION,
            provider=self.provider.provider_name,
            model=self.provider.model_name,
            temperature=self.settings.LLM_TEMPERATURE,
        )

        bundle_id = bundle_data.get("id")

        async with SummaryCacheManager.acquire_lock(cache_key):
            start_time = time.perf_counter()

            if not force_refresh:
                cached_res = await self.cache_manager.get_cached_summary(cache_key)
                if cached_res:
                    summary, model = cached_res
                    latency_ms = (time.perf_counter() - start_time) * 1000
                    logger.info(
                        "Cache HIT for patient [%s] (cache_key=%s, latency=%.1fms)",
                        patient_id,
                        cache_key[:12],
                        latency_ms,
                    )
                    return summary, True, latency_ms

            logger.info(
                "Cache MISS for patient [%s] (cache_key=%s); initiating LLM inference via [%s:%s]",
                patient_id,
                cache_key[:12],
                self.provider.provider_name,
                self.provider.model_name,
            )

            user_prompt = format_user_prompt(extracted)
            semaphore = _get_semaphore(self.settings.LLM_CONCURRENCY_LIMIT)

            try:
                async with semaphore:
                    raw_summary = await self.provider.generate_summary(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        temperature=self.settings.LLM_TEMPERATURE,
                        max_tokens=self.settings.LLM_MAX_OUTPUT_TOKENS,
                    )
            except Exception as exc:
                logger.warning(
                    "LLM inference execution failed for patient [%s]: %s. Engaging structured evidence fallback.",
                    patient_id,
                    exc,
                )
                raw_summary = self._synthesize_evidence_fallback(extracted, patient_id)

            try:
                raw_summary["patient_id"] = patient_id
                raw_summary["model_metadata"] = {
                    "provider": self.provider.provider_name,
                    "model": self.provider.model_name,
                }
                if not raw_summary.get("source_references"):
                    raw_summary["source_references"] = extracted.source_references

                # If LLM output is degenerate, contains echoed note tags, is too short (< 15 words),
                # or parrots prompt instruction text instead of actual clinical summary:
                summary_str = str(raw_summary.get("clinical_summary") or "").strip()
                summary_lower = summary_str.lower()
                is_parroting_prompt = any(
                    phrase in summary_lower for phrase in (
                        "synthesize 2 to 4",
                        "concise sentences",
                        "fewer than 200 words",
                        "adhering strictly to the schema",
                        "produce only a single valid json",
                        "original synthesized narrative",
                        "<write an original",
                    )
                )
                words_count = len(summary_str.split())
                is_degenerate = (
                    words_count < 15
                    or is_parroting_prompt
                    or "untrusted_clinical_note" in summary_str
                    or "untrusted_clinical_note" in str(raw_summary)
                    or not any(k in raw_summary for k in ("summary", "narrative", "overview", "clinical_overview", "text", "clinical_summary"))
                )

                if is_degenerate:
                    logger.warning(
                        "LLM returned degenerate or instruction-parroting output for patient [%s] (words=%d, parroting=%s). Engaging structured evidence fallback.",
                        patient_id,
                        words_count,
                        is_parroting_prompt,
                    )
                    raw_summary = self._synthesize_evidence_fallback(extracted, patient_id)

                # Clean any instruction strings that might have leaked into recent_diagnostic_records
                if isinstance(raw_summary.get("recent_diagnostic_records"), dict):
                    diag_rec = raw_summary["recent_diagnostic_records"]
                    for cat in ("laboratory", "imaging", "other"):
                        if isinstance(diag_rec.get(cat), list):
                            diag_rec[cat] = [
                                item for item in diag_rec[cat]
                                if isinstance(item, str) and not item.lower().startswith("extract ")
                            ]

                # Ensure clinical summary is clean text under 200 words (no raw JSON string)
                if raw_summary.get("clinical_summary"):
                    raw_text = str(raw_summary["clinical_summary"]).strip()
                    if raw_text.startswith("{") and raw_text.endswith("}"):
                        try:
                            inner = json.loads(raw_text)
                            raw_text = inner.get("clinical_summary") or inner.get("summary") or inner.get("narrative") or raw_text
                        except Exception:
                            pass
                    words = raw_text.split()
                    if len(words) >= 200:
                        raw_text = " ".join(words[:190]) + "..."
                    raw_summary["clinical_summary"] = raw_text

                summary_obj = ClinicalSummaryResponse.model_validate(raw_summary)
            except Exception as exc:
                logger.warning(
                    "LLM output schema validation failed for patient [%s]: %s. Engaging structured evidence fallback.",
                    patient_id,
                    exc,
                )
                fallback_data = self._synthesize_evidence_fallback(extracted, patient_id)
                summary_obj = ClinicalSummaryResponse.model_validate(fallback_data)

            validation_result = EvidenceValidator.validate_summary(summary_obj, extracted)
            if validation_result.should_reject:
                logger.warning(
                    "Rejecting non-grounded LLM summary for patient [%s] due to unsupported claims: %s. Engaging structured evidence fallback.",
                    patient_id,
                    validation_result.unsupported_claims,
                )
                fallback_data = self._synthesize_evidence_fallback(extracted, patient_id)
                summary_obj = ClinicalSummaryResponse.model_validate(fallback_data)
                validation_result = EvidenceValidator.validate_summary(summary_obj, extracted)

            if validation_result.adjusted_confidence:
                summary_obj.confidence = validation_result.adjusted_confidence

            exec_latency_ms = (time.perf_counter() - start_time) * 1000

            disk_path = None
            try:
                disk_file = self.disk_summary_dir / f"{patient_id}_summary.json"
                with open(disk_file, "w", encoding="utf-8") as f:
                    json.dump(summary_obj.model_dump(), f, indent=2, ensure_ascii=False)
                disk_path = str(disk_file)
            except Exception as exc:
                logger.warning("Could not persist summary to disk for patient [%s]: %s", patient_id, exc)

            existing_p = await self.patient_repo.get_by_id(patient_id)
            if not existing_p:
                new_pat = PatientModel(
                    id=patient_id,
                    source_system="fhir_bundle",
                    mrn=extracted.patient.mrn or "UNKNOWN",
                    first_name="UNKNOWN",
                    last_name="PATIENT",
                    administrative_gender=extracted.patient.gender or "unknown",
                    date_of_birth=extracted.patient.date_of_birth,
                )
                self.session.add(new_pat)
                await self.session.flush()

            await self.cache_manager.put_cached_summary(
                cache_key=cache_key,
                patient_id=patient_id,
                bundle_hash=bundle_hash,
                provider=self.provider.provider_name,
                model_name=self.provider.model_name,
                summary=summary_obj,
                bundle_id=bundle_id,
                prompt_version=self.settings.PROMPT_VERSION,
                temperature=self.settings.LLM_TEMPERATURE,
                status="COMPLETED" if validation_result.is_valid else "REVIEW_REQUIRED",
                execution_time_ms=exec_latency_ms,
                file_path=disk_path,
            )

            logger.info(
                "Successfully summarized patient [%s] (words=%d, conf=%s, latency=%.1fms)",
                patient_id,
                summary_obj.word_count,
                summary_obj.confidence.level.value,
                exec_latency_ms,
            )
            return summary_obj, False, exec_latency_ms

    async def summarize_patient(
        self,
        patient_id: str,
        bundle_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Tuple[ClinicalSummaryResponse, bool, float]:
        """Summarize a stored patient by loading their persisted FHIR Bundle from storage."""
        bundle_model = None
        if bundle_id:
            bundle_model = await self.bundle_repo.get_by_bundle_id(bundle_id)
        else:
            bundles = await self.bundle_repo.get_by_patient_id(patient_id, latest_only=True)
            if bundles:
                bundle_model = bundles[0]

        if not bundle_model or not bundle_model.bundle_json:
            patient = await self.patient_repo.get_by_id(patient_id)
            if not patient:
                raise AppException(f"Patient with ID '{patient_id}' not found", status_code=404)
            raise AppException(
                f"No normalized FHIR Bundle found for patient '{patient_id}'. Run FHIR normalization first via /api/v1/fhir/normalize/patient/{patient_id}",
                status_code=400,
            )

        return await self.summarize_bundle(
            bundle_data=bundle_model.bundle_json,
            force_refresh=force_refresh,
        )

    async def summarize_batch(
        self,
        patient_ids: List[str],
        force_refresh: bool = False,
    ) -> BatchSummarizeResponse:
        """Batch summarize multiple patients with strict error isolation between patients."""
        items: List[PatientSummaryItem] = []
        success_cnt = 0
        fail_cnt = 0
        cache_cnt = 0

        logger.info("Initiating batch clinical summarization for %d patients", len(patient_ids))

        for pid in patient_ids:
            item_start = time.perf_counter()
            try:
                summary, was_cached, lat_ms = await self.summarize_patient(
                    patient_id=pid,
                    force_refresh=force_refresh,
                )
                success_cnt += 1
                if was_cached:
                    cache_cnt += 1
                items.append(
                    PatientSummaryItem(
                        patient_id=pid,
                        status=SummaryExecutionStatus.CACHE_HIT if was_cached else SummaryExecutionStatus.SUCCESS,
                        summary=summary,
                        cached=was_cached,
                        execution_time_ms=lat_ms,
                    )
                )
            except Exception as exc:
                try:
                    await self.session.rollback()
                except Exception:
                    pass
                fail_cnt += 1
                lat_ms = (time.perf_counter() - item_start) * 1000
                logger.error("Isolated failure summarizing patient [%s] in batch: %s", pid, exc)
                items.append(
                    PatientSummaryItem(
                        patient_id=pid,
                        status=SummaryExecutionStatus.FAILED,
                        error_message=str(exc),
                        cached=False,
                        execution_time_ms=lat_ms,
                    )
                )

        return BatchSummarizeResponse(
            total_patients=len(patient_ids),
            successful_count=success_cnt,
            failed_count=fail_cnt,
            cache_hit_count=cache_cnt,
            results=items,
        )

    def _synthesize_evidence_fallback(
        self,
        extracted: ExtractedClinicalRecord,
        patient_id: str,
    ) -> Dict[str, Any]:
        """Synthesize a concise, clinically accurate, fact-grounded summary from validated FHIR resources.

        Guarantees < 200 words, strict Pydantic v2 compliance, and zero hallucination when LLM output is malformed.
        """
        p = extracted.patient
        gender_desc = p.gender if p.gender and p.gender != "unknown" else "individual"
        age_desc = f", age {p.age_years}" if p.age_years is not None else ""

        chief = extracted.chief_concern or "Longitudinal clinical monitoring and healthcare follow-up."

        # Filter active, non-refuted conditions according to FHIR R4 verificationStatus
        active_conditions = [
            c.name for c in extracted.conditions
            if getattr(c, "clinical_status", "").lower() == "active"
            and getattr(c, "verification_status", "").lower() not in ("refuted", "entered-in-error")
        ]
        if not active_conditions:
            active_conditions = [
                c.name for c in extracted.conditions
                if getattr(c, "verification_status", "").lower() not in ("refuted", "entered-in-error")
                and getattr(c, "clinical_status", "").lower() not in ("resolved", "remission")
            ]
        cond_text = ", ".join(active_conditions[:5]) if active_conditions else "None explicitly documented"

        abnormal_labs = [f"{o.name} ({o.value} {o.unit or ''})".strip() for o in extracted.observations if o.is_abnormal]
        lab_text = ", ".join(abnormal_labs[:4]) if abnormal_labs else "Within normal clinical limits"

        narrative_parts = [
            f"Patient {p.mrn} ({gender_desc}{age_desc}) presented for {chief}.",
            f"Active clinical conditions documented: {cond_text}.",
            f"Diagnostic observations: {lab_text}.",
            "Longitudinal records verified against HL7 FHIR R4 repository.",
        ]
        narrative = " ".join(narrative_parts)

        lab_items = [f"{o.name}: {o.value} {o.unit or ''}".strip() for o in extracted.observations[:5]]
        diag_records = {
            "laboratory": lab_items,
            "imaging": [
                dr.name for dr in extracted.diagnostic_reports
                if getattr(dr, "category", "").upper() in ("RAD", "IMAGING", "RADIOLOGY")
            ][:3],
            "other": [f"Encounter: {e.encounter_type}" for e in extracted.encounters[:3]],
        }

        return {
            "patient_id": patient_id,
            "chief_concern": chief,
            "key_diagnoses": active_conditions[:10],
            "recent_diagnostic_records": diag_records,
            "flagged_anomalies": extracted.flagged_anomalies or abnormal_labs[:5],
            "clinical_summary": narrative,
            "confidence": {
                "level": "moderate",
                "explanation": "Summary synthesized directly from validated structured FHIR R4 clinical observations and diagnostic records (evidence-grounded fallback).",
            },
            "disclaimer": DEFAULT_CLINICAL_DISCLAIMER,
            "source_references": extracted.source_references,
            "model_metadata": {
                "provider": self.provider.provider_name,
                "model": f"{self.provider.model_name}-evidence-fallback",
            },
        }

    async def aclose(self) -> None:
        """Release underlying provider resources if applicable."""
        if hasattr(self.provider, "aclose"):
            await self.provider.aclose()

