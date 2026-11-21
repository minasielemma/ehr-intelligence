"""High-level Clinical Summarizer interface and programmatic entry point.

Provides a unified facade for AI clinical document summarization, longitudinal patient
rollup, and FHIR Bundle synthesis across Ollama and cloud LLM providers.
"""

from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import BaseLLMProvider
from app.ai.providers.factory import get_llm_provider
from app.core.config import Settings, get_settings
from app.schemas.summary import (
    BatchSummarizeResponse,
    ClinicalSummaryResponse,
)

class ClinicalSummarizer:
    """Production interface for generating AI clinical summaries from validated FHIR Bundles."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        from app.services.clinical_summarization_service import ClinicalSummarizationService

        self.session = session
        self.settings = settings or get_settings()
        self.service = ClinicalSummarizationService(
            session=session,
            settings=self.settings,
            provider=provider,
        )

    async def summarize_bundle(
        self,
        bundle: Dict[str, Any],
        force_refresh: bool = False,
    ) -> ClinicalSummaryResponse:
        """Synthesize a validated HL7 FHIR R4 Bundle into a structured clinical summary."""
        summary, _, _ = await self.service.summarize_bundle(
            bundle_data=bundle,
            force_refresh=force_refresh,
        )
        return summary

    async def summarize_patient(
        self,
        patient_id: str,
        bundle_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> ClinicalSummaryResponse:
        """Load stored FHIR bundle for a patient and return clinical summary."""
        summary, _, _ = await self.service.summarize_patient(
            patient_id=patient_id,
            bundle_id=bundle_id,
            force_refresh=force_refresh,
        )
        return summary

    async def summarize_batch(
        self,
        patient_ids: List[str],
        force_refresh: bool = False,
    ) -> BatchSummarizeResponse:
        """Batch summarize multiple patients with error isolation."""
        return await self.service.summarize_batch(
            patient_ids=patient_ids,
            force_refresh=force_refresh,
        )


if __name__ == "__main__":
    from app.ai.cli import main
    main()
