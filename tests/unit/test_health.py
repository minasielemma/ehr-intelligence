"""Unit tests for FastAPI startup, health checks, and global exception handling."""

import pytest
from httpx import AsyncClient
from fastapi import FastAPI, status
from app.core.exceptions import NotFoundException, register_exception_handlers


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient) -> None:
    """Verify the root metadata endpoint is accessible and returns expected attributes."""
    response = await async_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "online"
    assert "version" in data
    assert "name" in data
    assert data["docs_url"] == "/api/v1/docs"


@pytest.mark.asyncio
async def test_health_check_endpoint(async_client: AsyncClient) -> None:
    """Verify health endpoint responds with system status and service details."""
    response = await async_client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "services" in data
    assert "database" in data["services"]
    assert "vector_store" in data["services"]


@pytest.mark.asyncio
async def test_api_v1_health_check_endpoint(async_client: AsyncClient) -> None:
    """Verify the versioned /api/v1/health endpoint functions identically."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["environment"] == "testing"
    assert data["services"]["database"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_openapi_schema_accessible(async_client: AsyncClient) -> None:
    """Verify OpenAPI v3 specification is generated and accessible."""
    response = await async_client.get("/api/v1/openapi.json")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "openapi" in data
    assert "/health" in data["paths"]
    assert "/api/v1/health" in data["paths"]


@pytest.mark.asyncio
async def test_centralized_exception_handler() -> None:
    """Verify custom AppException is formatted by registered exception handlers."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/trigger-error")
    async def trigger():
        raise NotFoundException("Patient EHR record not found", details={"resource_id": "P-123"})

    from httpx import ASGITransport
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-error")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"
        assert data["error"]["message"] == "Patient EHR record not found"
        assert data["error"]["details"]["resource_id"] == "P-123"
