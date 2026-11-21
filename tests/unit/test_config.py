"""Unit tests for centralized configuration and environment validation."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_default_settings_initialization() -> None:
    """Verify default configuration attributes load with valid values."""
    settings = Settings()
    assert settings.APP_NAME == "EHR Intelligence Platform"
    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.BACKEND_PORT == 8000
    assert "sentence-transformers" in settings.EMBEDDING_MODEL
    assert isinstance(settings.CORS_ORIGINS, list)


def test_settings_properties() -> None:
    """Verify computed configuration properties."""
    settings = Settings(
        APP_ENV="development",
        DATABASE_PATH="/custom/path/ehr.db",
        VECTOR_DB_HOST="chroma.internal",
        VECTOR_DB_PORT=8000,
    )
    assert settings.is_development is True
    assert settings.chroma_url == "http://chroma.internal:8000"
    assert settings.sqlite_url == "sqlite+aiosqlite:////custom/path/ehr.db"


def test_cors_origins_string_parsing() -> None:
    """Verify comma-separated CORS origins string parses to list of strings."""
    settings = Settings(CORS_ORIGINS="http://localhost:3000, https://myapp.com , http://127.0.0.1:3001")
    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "https://myapp.com",
        "http://127.0.0.1:3001",
    ]


def test_invalid_log_level_validation() -> None:
    """Verify invalid log level raises validation error."""
    with pytest.raises(ValidationError):
        Settings(LOG_LEVEL="SUPER_VERBOSE_UNKNOWN")


def test_get_settings_caching() -> None:
    """Verify get_settings returns a singleton instance."""
    instance_one = get_settings()
    instance_two = get_settings()
    assert instance_one is instance_two


def test_production_requires_auth_validation() -> None:
    """Verify that setting APP_ENV='production' without REQUIRE_AUTH=True raises ValidationError."""
    with pytest.raises(ValidationError, match="REQUIRE_AUTH must be True when APP_ENV is 'production'"):
        Settings(APP_ENV="production", REQUIRE_AUTH=False)

    prod_settings = Settings(APP_ENV="production", REQUIRE_AUTH=True)
    assert prod_settings.REQUIRE_AUTH is True

