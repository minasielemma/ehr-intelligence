"""Unit tests for LLM provider abstraction, Ollama error handling, and Cloud Adapters."""

import json
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import (
    LLMModelNotFoundError,
    LLMProviderError,
    LLMResponseParsingError,
    LLMTimeoutError,
    LLMUnavailableError,
    extract_json_from_llm_text,
)
from app.ai.providers.factory import get_llm_provider
from app.ai.providers.mock_provider import MockLLMProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.core.config import Settings


def test_provider_factory_resolution():
    """Verify factory returns appropriate provider adapter based on configuration."""
    s_ollama = Settings(LLM_PROVIDER="ollama")
    assert isinstance(get_llm_provider(s_ollama), OllamaProvider)

    s_anthropic = Settings(LLM_PROVIDER="anthropic")
    assert isinstance(get_llm_provider(s_anthropic), AnthropicProvider)

    s_openai = Settings(LLM_PROVIDER="openai")
    assert isinstance(get_llm_provider(s_openai), OpenAIProvider)

    s_mock = Settings(LLM_PROVIDER="mock")
    assert isinstance(get_llm_provider(s_mock), MockLLMProvider)

    with pytest.raises(LLMProviderError, match="Unsupported LLM provider"):
        get_llm_provider(s_ollama, provider_name="unsupported_provider")


def test_extract_json_from_various_formats():
    """Verify JSON extraction handles raw JSON, markdown blocks, and surrounding text."""
    # 1. Raw JSON
    raw = '{"patient_id": "p1", "summary": "ok"}'
    assert extract_json_from_llm_text(raw)["patient_id"] == "p1"

    # 2. Markdown fenced json block
    fenced = '```json\n{"patient_id": "p2", "summary": "ok"}\n```'
    assert extract_json_from_llm_text(fenced)["patient_id"] == "p2"

    # 3. Conversational preamble around JSON
    conversational = 'Here is the summary:\n{"patient_id": "p3", "summary": "ok"}\nHope this helps!'
    assert extract_json_from_llm_text(conversational)["patient_id"] == "p3"

    # 4. Invalid text raises LLMResponseParsingError
    with pytest.raises(LLMResponseParsingError):
        extract_json_from_llm_text("This is purely plain text without any json brackets.")


@pytest.mark.asyncio
async def test_ollama_provider_health_check_healthy():
    """Verify Ollama health check passes when server is responsive and model is present."""
    mock_tags = {
        "models": [
            {"name": "gemma3:12b", "model": "gemma3:12b"},
            {"name": "llama3.1:8b", "model": "llama3.1:8b"},
        ]
    }

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=mock_tags)
    )
    client = httpx.AsyncClient(transport=transport)

    provider = OllamaProvider(
        base_url="http://mock-ollama:11434",
        model="gemma3:12b",
        client=client,
    )
    health = await provider.check_health()
    assert health["status"] == "healthy"
    assert health["available"] is True
    assert health["provider"] == "ollama"
    assert health["model"] == "gemma3:12b"


@pytest.mark.asyncio
async def test_ollama_provider_health_check_missing_model():
    """Verify Ollama health check reports degraded when model is not downloaded."""
    mock_tags = {"models": [{"name": "llama3.1:8b"}]}

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=mock_tags)
    )
    client = httpx.AsyncClient(transport=transport)

    provider = OllamaProvider(
        base_url="http://mock-ollama:11434",
        model="gemma3:12b",  # Model not in mock_tags!
        client=client,
    )
    health = await provider.check_health()
    assert health["status"] == "degraded"
    assert health["available"] is False
    assert "not downloaded" in health["details"]["error"]


@pytest.mark.asyncio
async def test_ollama_provider_inference_success():
    """Verify successful Ollama inference with chat endpoint and model metadata attachment."""
    expected_response = {
        "patient_id": "pat-ollama",
        "chief_concern": "Follow up",
        "key_diagnoses": ["Hypertension"],
        "recent_diagnostic_records": {"laboratory": [], "imaging": [], "other": []},
        "flagged_anomalies": [],
        "clinical_summary": "Patient is in stable condition.",
        "confidence": {"level": "high", "explanation": "Grounded"},
        "disclaimer": "AI-generated summary. Not a clinical diagnosis or medical decision.",
        "source_references": ["Patient/pat-ollama"],
    }

    mock_ollama_payload = {
        "message": {
            "role": "assistant",
            "content": json.dumps(expected_response),
        }
    }

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=mock_ollama_payload)
    )
    client = httpx.AsyncClient(transport=transport)

    provider = OllamaProvider(
        base_url="http://mock-ollama:11434",
        model="gemma3:12b",
        client=client,
    )

    result = await provider.generate_summary(
        system_prompt="System instructions",
        user_prompt="User data",
    )

    assert result["patient_id"] == "pat-ollama"
    assert result["model_metadata"]["provider"] == "ollama"
    assert result["model_metadata"]["model"] == "gemma3:12b"


@pytest.mark.asyncio
async def test_ollama_provider_model_not_found_raises():
    """Verify HTTP 404 from Ollama raises LLMModelNotFoundError."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, text="model 'unknown:latest' not found")
    )
    client = httpx.AsyncClient(transport=transport)

    provider = OllamaProvider(
        base_url="http://mock-ollama:11434",
        model="unknown:latest",
        client=client,
    )

    with pytest.raises(LLMModelNotFoundError, match="not found in Ollama"):
        await provider.generate_summary("system", "user")


@pytest.mark.asyncio
async def test_anthropic_provider_missing_credentials_fails():
    """Verify Anthropic provider raises 401 when API key is missing."""
    settings = Settings(ANTHROPIC_API_KEY=None)
    provider = AnthropicProvider(settings=settings, api_key=None)

    with pytest.raises(LLMProviderError, match="ANTHROPIC_API_KEY must be provided"):
        await provider.generate_summary("system", "user")


@pytest.mark.asyncio
async def test_anthropic_provider_mocked_inference():
    """Verify Anthropic provider with mock client returns parsed summary."""
    mock_block = MagicMock()
    mock_block.text = json.dumps({
        "patient_id": "pat-claude",
        "clinical_summary": "Claude generated summary.",
        "confidence": {"level": "high", "explanation": "Claude rationale"},
    })

    mock_resp = MagicMock()
    mock_resp.content = [mock_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_resp)

    provider = AnthropicProvider(
        api_key="mock-anthropic-key",
        model="claude-3-5-sonnet-20241022",
        client=mock_client,
    )

    result = await provider.generate_summary("system", "user")
    assert result["patient_id"] == "pat-claude"
    assert result["model_metadata"]["provider"] == "anthropic"
    assert result["model_metadata"]["model"] == "claude-3-5-sonnet-20241022"


@pytest.mark.asyncio
async def test_openai_provider_missing_credentials_fails():
    """Verify OpenAI provider raises 401 when API key is missing."""
    settings = Settings(OPENAI_API_KEY=None)
    provider = OpenAIProvider(settings=settings, api_key=None)

    with pytest.raises(LLMProviderError, match="OPENAI_API_KEY must be provided"):
        await provider.generate_summary("system", "user")


@pytest.mark.asyncio
async def test_openai_provider_mocked_inference():
    """Verify OpenAI provider with mock client returns parsed summary with json_object format."""
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "patient_id": "pat-gpt",
        "clinical_summary": "OpenAI generated summary.",
        "confidence": {"level": "high", "explanation": "GPT rationale"},
    })

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    provider = OpenAIProvider(
        api_key="mock-openai-key",
        model="gpt-4o-mini",
        client=mock_client,
    )

    result = await provider.generate_summary("system", "user")
    assert result["patient_id"] == "pat-gpt"
    assert result["model_metadata"]["provider"] == "openai"
    assert result["model_metadata"]["model"] == "gpt-4o-mini"
    # Ensure json_object format was requested
    mock_client.chat.completions.create.assert_called_once()
    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs.get("response_format") == {"type": "json_object"}


def test_provider_factory_model_override():
    """Verify get_llm_provider passes model_name to created provider adapters."""
    s = Settings(LLM_PROVIDER="mock")
    provider = get_llm_provider(s, model_name="custom-model-override")
    assert provider.model_name == "custom-model-override"

    s_ollama = Settings(LLM_PROVIDER="ollama")
    ollama_prov = get_llm_provider(s_ollama, model_name="llama3.2:3b")
    assert ollama_prov.model_name == "llama3.2:3b"


@pytest.mark.asyncio
async def test_ollama_client_lifecycle_and_aclose():
    """Verify OllamaProvider creates persistent client and closes it via aclose."""
    provider = OllamaProvider()
    client1 = await provider._get_client()
    client2 = await provider._get_client()
    assert client1 is client2, "OllamaProvider must reuse persistent client"
    assert not client1.is_closed

    await provider.aclose()
    assert provider._client is None
    assert client1.is_closed, "aclose must close underlying httpx client"

