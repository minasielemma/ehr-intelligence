"""Anthropic Claude API adapter supporting official Python SDK, direct httpx fallback, and mockable execution."""

import asyncio
import os
import time
from typing import Any, Dict, Optional
import httpx

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


class AnthropicProvider(BaseLLMProvider):
    """Adapter for Anthropic Claude API models with dual SDK and direct httpx support."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        super().__init__(settings)
        self._api_key = api_key or self.settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model or self.settings.ANTHROPIC_MODEL
        self._client = client
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    async def aclose(self) -> None:
        """Close any persistent HTTP clients."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return or create a persistent httpx.AsyncClient for direct Anthropic API calls."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=float(self.settings.LLM_TIMEOUT))
        return self._http_client

    def _get_anthropic_client(self) -> Any:
        """Instantiate official AsyncAnthropic client if not injected."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise LLMProviderError(
                "ANTHROPIC_API_KEY must be provided via settings or environment to use anthropic provider",
                status_code=401,
            )

        try:
            import anthropic
            return anthropic.AsyncAnthropic(api_key=self._api_key, timeout=float(self.settings.LLM_TIMEOUT))
        except ImportError:
            return None

    async def check_health(self) -> Dict[str, Any]:
        """Validate Anthropic provider readiness and credential presence."""
        if not self._api_key:
            return {
                "status": "unconfigured",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": False,
                "latency_ms": None,
                "details": {
                    "error": "ANTHROPIC_API_KEY is not configured",
                    "instruction": "Set ANTHROPIC_API_KEY in environment or .env file",
                },
            }

        start = time.perf_counter()
        if self._client is not None:
            return {
                "status": "healthy",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": True,
                "latency_ms": (time.perf_counter() - start) * 1000,
                "details": {"client_type": type(self._client).__name__},
            }

        try:
            http_client = self._get_http_client()
            headers = {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            # Send a minimal probe to test authentication
            resp = await http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json={
                    "model": self._model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
            latency = (time.perf_counter() - start) * 1000

            if resp.status_code == 200:
                return {
                    "status": "healthy",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": True,
                    "latency_ms": latency,
                    "details": {"authenticated": True},
                }
            elif resp.status_code == 400:
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                err_msg = body.get("error", {}).get("message", resp.text)
                is_credit_issue = "credit balance" in err_msg.lower() or "billing" in err_msg.lower()
                return {
                    "status": "credit_exhausted" if is_credit_issue else "error",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": False,
                    "latency_ms": latency,
                    "details": {
                        "error": err_msg,
                        "authenticated": True,
                        "credit_exhausted": is_credit_issue,
                    },
                }
            elif resp.status_code == 401:
                return {
                    "status": "unauthorized",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": False,
                    "latency_ms": latency,
                    "details": {"error": "Invalid Anthropic API key (401 Unauthorized)", "authenticated": False},
                }
            else:
                return {
                    "status": "error",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": False,
                    "latency_ms": latency,
                    "details": {"error": f"Anthropic HTTP {resp.status_code}: {resp.text}"},
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
        """Execute summarization via Claude Messages API."""
        if not self._api_key and self._client is None:
            raise LLMProviderError(
                "ANTHROPIC_API_KEY must be provided via settings or environment to use anthropic provider",
                status_code=401,
            )

        temp = temperature if temperature is not None else self.settings.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else self.settings.LLM_MAX_OUTPUT_TOKENS

        sdk_client = self._get_anthropic_client()
        content_text = ""

        if sdk_client is not None:
            try:
                response = await sdk_client.messages.create(
                    model=self._model,
                    max_tokens=tokens,
                    temperature=temp,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_prompt},
                    ],
                )
                if hasattr(response, "content") and response.content:
                    for block in response.content:
                        if hasattr(block, "text"):
                            content_text += block.text
                        elif isinstance(block, dict) and "text" in block:
                            content_text += block["text"]
            except Exception as exc:
                err_msg = str(exc)
                if "authentication" in err_msg.lower() or "api_key" in err_msg.lower():
                    raise LLMProviderError(f"Anthropic authentication failed: {exc}", status_code=401)
                elif "timeout" in err_msg.lower():
                    raise LLMTimeoutError(f"Anthropic API request timed out: {exc}")
                raise LLMProviderError(f"Anthropic API error: {exc}")
        else:
            # Fallback to direct HTTP request using httpx
            http_client = self._get_http_client()
            headers = {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": self._model,
                "max_tokens": tokens,
                "temperature": temp,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt},
                ],
            }
            try:
                resp = await http_client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(f"Anthropic API request timed out: {exc}")
            except Exception as exc:
                raise LLMUnavailableError(f"Anthropic service unreachable: {exc}")

            if resp.status_code == 401:
                raise LLMProviderError(f"Anthropic authentication failed: {resp.text}", status_code=401)
            elif resp.status_code == 400:
                err_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                err_msg = err_json.get("error", {}).get("message", resp.text)
                raise LLMProviderError(f"Anthropic API error: {err_msg}", status_code=400)
            elif resp.status_code != 200:
                raise LLMProviderError(f"Anthropic API returned status {resp.status_code}: {resp.text}", status_code=resp.status_code)

            data = resp.json()
            content_text = "".join(b.get("text", "") for b in data.get("content", []))

        parsed_json = extract_json_from_llm_text(content_text)
        parsed_json["model_metadata"] = {
            "provider": self.provider_name,
            "model": self.model_name,
        }
        return parsed_json
