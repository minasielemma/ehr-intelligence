"""Provider-independent abstract base class and standardized exception hierarchy for LLM adapters."""

from abc import ABC, abstractmethod
import json
import re
from typing import Any, Dict, Optional

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMProviderError(AppException):
    """Base exception for all LLM provider operational failures."""
    def __init__(self, message: str, status_code: int = 502, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, status_code=status_code)
        self.details = details or {}


class LLMUnavailableError(LLMProviderError):
    """Raised when the target LLM provider endpoint is unreachable or down."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, status_code=503, details=details)


class LLMModelNotFoundError(LLMProviderError):
    """Raised when the requested model is not downloaded or unavailable on the provider."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, status_code=404, details=details)


class LLMTimeoutError(LLMProviderError):
    """Raised when inference exceeds configured timeout limits."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, status_code=504, details=details)


class LLMResponseParsingError(LLMProviderError):
    """Raised when the provider output fails JSON deserialization or schema compliance."""
    def __init__(self, message: str, raw_response: Optional[str] = None) -> None:
        super().__init__(message, status_code=502, details={"raw_response": raw_response})


def extract_json_from_llm_text(text: str) -> Dict[str, Any]:
    """Robustly extract and parse JSON payload from model output text.

    Handles pure JSON, markdown fenced blocks (```json ... ```), and raw un-fenced responses.
    """
    if not text or not text.strip():
        raise LLMResponseParsingError("LLM returned an empty response")

    cleaned = text.strip()

    # 1. Attempt direct JSON parsing
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code blocks
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if code_block_match:
        extracted = code_block_match.group(1).strip()
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    # 3. Locate outer-most JSON object brackets
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx : end_idx + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMResponseParsingError(f"Failed to parse inner JSON object: {exc}", raw_response=cleaned)

    raise LLMResponseParsingError("No valid JSON object structure found in LLM output", raw_response=cleaned)


class BaseLLMProvider(ABC):
    """Common interface for all clinical LLM providers (Ollama, Anthropic, OpenAI)."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the unique provider name (e.g. 'ollama', 'anthropic', 'openai')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the active model name."""
        pass

    @abstractmethod
    async def generate_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute clinical summarization prompt and return structured JSON dictionary.

        Args:
            system_prompt: System directive instructions.
            user_prompt: Structured clinical context and untrusted notes.
            temperature: Optional sampling temperature override.
            max_tokens: Optional token limit override.

        Returns:
            Dict conforming to the ClinicalSummaryResponse schema.
        """
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """Verify provider endpoint responsiveness and model availability.

        Returns:
            Dict with keys: status, provider, model, available, latency_ms, details.
        """
        pass

    async def aclose(self) -> None:
        """Gracefully release and close underlying connection pools or clients."""
        pass
