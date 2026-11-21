"""Pytest fixtures for EHR Intelligence Platform test suite."""

from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.main import create_application
from app.models.database import init_db


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Return test-specific settings with isolated temporary storage per test."""
    db_path = str(tmp_path / "test_ehr.db")

    return Settings(
        APP_NAME="EHR Intelligence Test Platform",
        APP_ENV="testing",
        DEBUG=True,
        API_V1_PREFIX="/api/v1",
        DATABASE_PATH=db_path,
        VECTOR_DB_HOST="localhost",
        VECTOR_DB_PORT=8001,
        LOG_LEVEL="DEBUG",
        CORS_ORIGINS=["http://localhost:3000"],
    )


@pytest.fixture
async def async_client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """Provide an asynchronous HTTP client configured with isolated database storage."""
    # Ensure tables exist in the isolated test database
    await init_db(database_path=test_settings.DATABASE_PATH)

    app = create_application()
    app.dependency_overrides[get_settings] = lambda: test_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
