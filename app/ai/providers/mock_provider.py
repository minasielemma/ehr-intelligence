"""Mock LLM provider for deterministic offline testing and synthetic clinical benchmarking."""

from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, Optional

from app.ai.providers.base import BaseLLMProvider
from app.core.config import Settings, get_settings


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock provider returning schema-compliant clinical summaries without network calls."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        model: Optional[str] = None,
        canned_response: Optional[Dict[str, Any]] = None,
        fail_with: Optional[Exception] = None,
    ) -> None:
        super().__init__(settings)
        self._model = model or "mock-clinical-summarizer-v1"
        self.canned_response = canned_response
        self.fail_with = fail_with
        self.call_count = 0
        self.last_system_prompt: Optional[str] = None
        self.last_user_prompt: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    async def check_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider": self.provider_name,
            "model": self.model_name,
            "available": True,
            "latency_ms": 1.0,
            "details": {"mock": True},
        }

    async def generate_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt

        if self.fail_with:
            raise self.fail_with

        if self.canned_response:
            resp = dict(self.canned_response)
            resp["model_metadata"] = {
                "provider": self.provider_name,
                "model": self.model_name,
            }
            return resp

        # Parse patient_id from user prompt
        patient_id = "pat-mock"
        p_match = re.search(r"patient ID '([^']+)'", user_prompt)
        if p_match:
            patient_id = p_match.group(1)

        # Extract diagnoses and observations from prompt context if present
        diagnoses = []
        diag_matches = re.findall(r'"name":\s*"([^"]+)"', user_prompt)
        if diag_matches:
            diagnoses = diag_matches[:3]

        return {
            "patient_id": patient_id,
            "chief_concern": "Follow-up clinical evaluation and diagnostic review",
            "key_diagnoses": diagnoses if diagnoses else ["Essential Hypertension"],
            "recent_diagnostic_records": {
                "laboratory": ["Serum Creatinine 1.1 mg/dL", "Hemoglobin A1c 5.6%"],
                "imaging": ["Chest X-Ray Normal"],
                "other": ["Blood Pressure 128/82 mmHg"],
            },
            "flagged_anomalies": [],
            "clinical_summary": f"Patient {patient_id} evaluated for routine clinical review. Vital signs and documented diagnostic records reviewed with stable cardiopulmonary and metabolic parameters.",
            "confidence": {
                "level": "high",
                "explanation": "Summary directly grounded in extracted verified clinical records.",
            },
            "disclaimer": "AI-generated summary. Not a clinical diagnosis or medical decision.",
            "source_references": [f"Patient/{patient_id}"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_metadata": {
                "provider": self.provider_name,
                "model": self.model_name,
            },
        }
