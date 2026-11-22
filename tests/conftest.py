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
    vec_path = str(tmp_path / "vector_store")

    return Settings(
        APP_NAME="EHR Intelligence Test Platform",
        APP_ENV="testing",
        DEBUG=True,
        API_V1_PREFIX="/api/v1",
        DATABASE_PATH=db_path,
        VECTOR_STORE_PATH=vec_path,
        VECTOR_DB_HOST="localhost",
        VECTOR_DB_PORT=8001,
        LOG_LEVEL="DEBUG",
        CORS_ORIGINS=["http://localhost:3000"],
        LLM_PROVIDER="mock",
        OLLAMA_BASE_URL="http://172.25.0.1:11434",
    )


@pytest.fixture
def isolate_vector_store(test_settings: Settings, monkeypatch):
    """Ensure vector store is strictly isolated to a temporary directory per test."""
    import app.search.vector_store as vs_module
    test_store = vs_module.VectorStore(persist_directory=test_settings.VECTOR_STORE_PATH)
    monkeypatch.setattr(vs_module, "_GLOBAL_VECTOR_STORE", test_store)
    yield test_store


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
