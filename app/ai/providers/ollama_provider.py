"""Production-ready Ollama LLM provider adapter using local HTTP API."""

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, List, Optional
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.ai.providers.base import (
    BaseLLMProvider,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMResponseParsingError,
    LLMTimeoutError,
    LLMUnavailableError,
    extract_json_from_llm_text,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OllamaProvider(BaseLLMProvider):
    """Local Ollama LLM Provider supporting structured JSON generation, health checks, and retry policies."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(settings)
        self._base_url = (base_url or self.settings.OLLAMA_BASE_URL).rstrip("/")
        self._model = model or self.settings.OLLAMA_MODEL
        self._client = client
        self._owns_client: bool = client is None
        self._resolved_base_url: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._resolved_base_url or self._base_url

    async def _get_client(self) -> httpx.AsyncClient:
        """Provide or create persistent async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=float(self.settings.LLM_TIMEOUT))
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Gracefully release and close underlying connection pool if owned."""
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _resolve_endpoint(self, client: httpx.AsyncClient) -> str:
        """Intelligently probe and resolve the reachable Ollama endpoint.

        Handles Docker container-to-host networking (localhost vs host.docker.internal vs gateway).
        """
        if self._resolved_base_url:
            return self._resolved_base_url

        candidate_urls = [self._base_url]
        if "localhost" in self._base_url:
            candidate_urls.extend(["http://host.docker.internal:11434", "http://172.25.0.1:11434"])
        elif "host.docker.internal" in self._base_url:
            candidate_urls.extend(["http://172.25.0.1:11434", "http://localhost:11434"])

        for url in candidate_urls:
            try:
                resp = await client.get(f"{url}/api/tags", timeout=3.0)
                if resp.status_code == 200:
                    self._resolved_base_url = url
                    logger.debug("Resolved reachable Ollama endpoint: %s", url)
                    return url
            except Exception:
                continue

        # If all probes fail, default to configured URL
        self._resolved_base_url = self._base_url
        return self._base_url

    async def check_health(self) -> Dict[str, Any]:
        """Verify Ollama server connectivity and model availability."""
        client = await self._get_client()
        start_time = time.perf_counter()

        try:
            resolved_url = await self._resolve_endpoint(client)
            resp = await client.get(f"{resolved_url}/api/tags", timeout=5.0)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if resp.status_code != 200:
                return {
                    "status": "degraded",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": False,
                    "latency_ms": latency_ms,
                    "details": {"error": f"Ollama HTTP {resp.status_code}: {resp.text}"},
                }

            data = resp.json()
            models_list = data.get("models", [])
            installed_models = [m.get("name", "") for m in models_list]

            # Check if requested model or matching prefix/tag is installed
            model_matched = any(
                self._model == name or name.startswith(f"{self._model}:") or self._model.startswith(f"{name}:")
                for name in installed_models
            )

            if not model_matched:
                return {
                    "status": "degraded",
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "available": False,
                    "latency_ms": latency_ms,
                    "details": {
                        "error": f"Model '{self._model}' is not downloaded in Ollama",
                        "installed_models": installed_models,
                        "instruction": f"Run 'ollama pull {self._model}' on the host server",
                    },
                }

            return {
                "status": "healthy",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": True,
                "latency_ms": latency_ms,
                "details": {
                    "endpoint": resolved_url,
                    "installed_models_count": len(installed_models),
                },
            }

        except httpx.ConnectError as exc:
            return {
                "status": "unavailable",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": False,
                "latency_ms": None,
                "details": {
                    "error": f"Connection refused to Ollama server at '{self._base_url}': {exc}",
                    "instruction": "Ensure Ollama service is running via 'ollama serve'",
                },
            }
        except httpx.TimeoutException as exc:
            return {
                "status": "timeout",
                "provider": self.provider_name,
                "model": self.model_name,
                "available": False,
                "latency_ms": None,
                "details": {"error": f"Timeout connecting to Ollama: {exc}"},
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
        """Execute clinical summarization using Ollama local HTTP API with retry policies."""
        temp = temperature if temperature is not None else self.settings.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else self.settings.LLM_MAX_OUTPUT_TOKENS

        max_retries = self.settings.LLM_MAX_RETRIES
        backoff = self.settings.LLM_BACKOFF_FACTOR

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                return await self._execute_inference(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temp,
                    max_tokens=tokens,
                )
            except (LLMUnavailableError, LLMTimeoutError) as exc:
                last_error = exc
                if attempt < max_retries:
                    wait_time = backoff ** attempt
                    logger.warning(
                        "Ollama inference attempt %d/%d failed with %s: retrying in %.2fs",
                        attempt,
                        max_retries,
                        type(exc).__name__,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("Ollama inference exhausted all %d attempts: %s", max_retries, exc)
                    raise exc
            except (LLMModelNotFoundError, LLMResponseParsingError) as exc:
                # Do not retry non-transient model-not-found or parsing defects
                raise exc

        if last_error:
            raise last_error
        raise LLMProviderError("Ollama inference failed unexpectedly")

    async def _execute_inference(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """Send chat completion request to Ollama with format='json'."""
        client = await self._get_client()
        resolved_url = await self._resolve_endpoint(client)
        chat_endpoint = f"{resolved_url}/api/chat"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            resp = await client.post(
                chat_endpoint,
                json=payload,
                timeout=float(self.settings.LLM_TIMEOUT),
            )
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"Cannot connect to Ollama at '{resolved_url}': service unavailable",
                details={"endpoint": resolved_url, "error": str(exc)},
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama inference timed out after {self.settings.LLM_TIMEOUT}s",
                details={"model": self._model, "timeout": self.settings.LLM_TIMEOUT},
            )
        except Exception as exc:
            raise LLMProviderError(f"Unexpected HTTP communication error with Ollama: {exc}")

        if resp.status_code == 404:
            raise LLMModelNotFoundError(
                f"Model '{self._model}' not found in Ollama. Pull it using 'ollama pull {self._model}'",
                details={"status_code": 404, "response": resp.text},
            )
        elif resp.status_code != 200:
            raise LLMProviderError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json()
        message = data.get("message", {})
        content = message.get("content", "")

        if not content:
            # Check fallback to response field if /api/generate was returned
            content = data.get("response", "")

        parsed_json = extract_json_from_llm_text(content)

        # Inject / guarantee model metadata matches actual execution
        parsed_json["model_metadata"] = {
            "provider": self.provider_name,
            "model": self.model_name,
        }

        return parsed_json
