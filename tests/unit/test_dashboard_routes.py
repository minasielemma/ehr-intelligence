"""Unit tests for the dashboard analytics and metrics API endpoint."""

import pytest
from httpx import AsyncClient
from fastapi import status


@pytest.mark.asyncio
async def test_dashboard_stats_endpoint(async_client: AsyncClient) -> None:
    """Verify /api/v1/dashboard/stats returns aggregate database metrics and domain distribution."""
    response = await async_client.get(
        "/api/v1/dashboard/stats",
        headers={"X-API-Key": "dev-test-key"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "total_patients" in data
    assert "total_records" in data
    assert "total_fhir_bundles" in data
    assert "total_fhir_resources" in data
    assert "domain_distribution" in data
    assert isinstance(data["domain_distribution"], list)
    assert "recent_jobs" in data
    assert "recent_patients" in data
    assert data["system_status"] == "healthy"
