"""OpenAI API adapter supporting official Python SDK and mockable execution."""

import asyncio
import os
import time
from typing import Any, Dict, Optional

from app.ai.providers.base import (
    BaseLLMProvider,
    LLMProviderError,
    LLMResponseParsingError,
    LLMTimeoutError,
    LLMUnavailableError,
    extract_json_from_llm_text,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """Adapter for OpenAI Chat Completions API with native JSON object formatting."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        super().__init__(settings)
        self._api_key = api_key or self.settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
        self._model = model or self.settings.OPENAI_MODEL
        self._client = client

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def _get_openai_client(self) -> Any:
        """Instantiate official AsyncOpenAI client if not injected."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise LLMProviderError(
                "OPENAI_API_KEY must be provided via settings or environment to use openai provider",
                status_code=401,
            )

        try:
            import openai
            return openai.AsyncOpenAI(api_key=self._api_key, timeout=float(self.settings.LLM_TIMEOUT))
        except ImportError:
            raise LLMProviderError(
                "OpenAI SDK is not installed. Install via: pip install openai",
                status_code=500,
            )

    async def check_health(self) -> Dict[str, Any]:
        """Validate OpenAI provider readiness and credential presence."""
        if not self._api_key:
            return {
                "status": "unconfigured",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": False,
                "latency_ms": None,
                "details": {
                    "error": "OPENAI_API_KEY is not configured",
                    "instruction": "Set OPENAI_API_KEY in environment or .env file",
                },
            }

        start = time.perf_counter()
        try:
            client = self._get_openai_client()
            if hasattr(client, "chat"):
                latency = (time.perf_counter() - start) * 1000
                return {
                    "status": "healthy",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": True,
                    "latency_ms": latency,
                    "details": {"client_type": type(client).__name__},
                }
            return {
                "status": "healthy",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": True,
                "latency_ms": 0.0,
            }
        except Exception as exc:
            return {
                "status": "error",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": False,
                "latency_ms": None,
                "details": {"error": str(exc)},
            }

    async def generate_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute summarization via OpenAI Chat Completions API with response_format json_object."""
        client = self._get_openai_client()
        temp = temperature if temperature is not None else self.settings.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else self.settings.LLM_MAX_OUTPUT_TOKENS

        try:
            response = await client.chat.completions.create(
                model=self._model,
                temperature=temp,
                max_tokens=tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            err_msg = str(exc)
            if "authentication" in err_msg.lower() or "api_key" in err_msg.lower():
                raise LLMProviderError(f"OpenAI authentication failed: {exc}", status_code=401)
            elif "timeout" in err_msg.lower():
                raise LLMTimeoutError(f"OpenAI API request timed out: {exc}")
            raise LLMProviderError(f"OpenAI API error: {exc}")

        content_text = response.choices[0].message.content or ""
        parsed_json = extract_json_from_llm_text(content_text)
        parsed_json["model_metadata"] = {
            "provider": self.provider_name,
            "model": self.model_name,
        }
        return parsed_json
