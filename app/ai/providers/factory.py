"""Factory for instantiating configured LLM provider adapters."""

from typing import Optional

from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import BaseLLMProvider, LLMProviderError
from app.ai.providers.mock_provider import MockLLMProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_llm_provider(
    settings: Optional[Settings] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> BaseLLMProvider:
    """Instantiate and return the appropriate LLM provider based on settings or override.

    Args:
        settings: Application settings singleton.
        provider_name: Explicit provider override (e.g. 'ollama', 'anthropic', 'openai', 'mock').
        model_name: Optional explicit model name override.

    Returns:
        Instance implementing BaseLLMProvider.
    """
    active_settings = settings or get_settings()
    target_provider = (provider_name or active_settings.LLM_PROVIDER).lower()

    if target_provider == "ollama":
        return OllamaProvider(settings=active_settings, model=model_name)
    elif target_provider == "anthropic":
        return AnthropicProvider(settings=active_settings, model=model_name)
    elif target_provider == "openai":
        return OpenAIProvider(settings=active_settings, model=model_name)
    elif target_provider == "mock":
        return MockLLMProvider(settings=active_settings, model=model_name)
    else:
        raise LLMProviderError(f"Unsupported LLM provider requested: '{target_provider}'")
