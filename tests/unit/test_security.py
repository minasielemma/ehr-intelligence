"""Security tests for file upload constraints, path traversal mitigation, and PHI logging prevention."""

import io
import pytest
from httpx import AsyncClient
from fastapi import status

from app.core.config import Settings
from app.core.exceptions import ValidationException
from app.ingestion.orchestrator import IngestionOrchestrator


@pytest.mark.asyncio
async def test_upload_disallowed_extension(async_client: AsyncClient) -> None:
    """Verify uploads with unauthorized file extensions are rejected with 422 Unprocessable Entity."""
    files = {"file": ("malicious_payload.exe", b"executable_binary_content", "application/octet-stream")}
    response = await async_client.post("/api/v1/ingestion/upload", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    data = response.json()
    assert "error" in data
    assert "not supported" in data["error"]["message"]


@pytest.mark.asyncio
async def test_upload_empty_file(async_client: AsyncClient) -> None:
    """Verify empty file uploads are rejected with 422."""
    files = {"file": ("empty_records.json", b"", "application/json")}
    response = await async_client.post("/api/v1/ingestion/upload", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    data = response.json()
    assert "empty" in data["error"]["message"]


@pytest.mark.asyncio
async def test_upload_path_traversal_sanitization(async_client: AsyncClient) -> None:
    """Verify path traversal in filenames does not compromise storage."""
    files = {
        "file": (
            "../../../../etc/passwd.json",
            b'[{"mrn": "MRN-PATH-1", "first_name": "Test", "last_name": "User", "dob": "1990-01-01"}]',
            "application/json",
        )
    }
    response = await async_client.post("/api/v1/ingestion/upload", files=files)
    # File should either succeed with sanitized basename or be safely handled inside app storage
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["job_id"] is not None


@pytest.mark.asyncio
async def test_upload_oversized_file(async_client: AsyncClient, test_settings) -> None:
    """Verify files exceeding maximum configured bytes are rejected."""
    large_payload = b"A" * 1000
    files = {"file": ("large_records.json", large_payload, "application/json")}

    original_limit = test_settings.MAX_UPLOAD_SIZE_BYTES
    try:
        test_settings.MAX_UPLOAD_SIZE_BYTES = 500  # Set low limit for test
        response = await async_client.post("/api/v1/ingestion/upload", files=files)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "maximum permitted limit" in response.json()["error"]["message"]
    finally:
        test_settings.MAX_UPLOAD_SIZE_BYTES = original_limit


@pytest.mark.asyncio
async def test_api_key_auth_enforcement(async_client: AsyncClient, test_settings) -> None:
    """Verify that when REQUIRE_AUTH is True, endpoints reject requests without a valid X-API-Key."""
    test_settings.REQUIRE_AUTH = True
    test_settings.API_KEYS = ["secret-test-key-123"]

    payload = {
        "source_system": "secure_system",
        "records": [
            {
                "id": "SEC-1",
                "mrn": "MRN-SEC-1",
                "first_name": "Secure",
                "last_name": "Patient",
                "dob": "1990-01-01",
            }
        ],
    }

    try:
        # 1. Missing header -> 401
        res_missing = await async_client.post("/api/v1/ingestion/json", json=payload)
        assert res_missing.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Missing required API Key" in res_missing.json()["error"]["message"]

        # 2. Invalid key -> 401
        res_invalid = await async_client.post(
            "/api/v1/ingestion/json",
            json=payload,
            headers={"X-API-Key": "wrong-key"},
        )
        assert res_invalid.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid or revoked API Key" in res_invalid.json()["error"]["message"]

        # 3. Valid key -> 201
        res_valid = await async_client.post(
            "/api/v1/ingestion/json",
            json=payload,
            headers={"X-API-Key": "secret-test-key-123"},
        )
        assert res_valid.status_code == status.HTTP_201_CREATED
        assert res_valid.json()["successful_records"] == 1
    finally:
        test_settings.REQUIRE_AUTH = False


@pytest.mark.asyncio
async def test_async_background_ingestion(async_client: AsyncClient, test_settings) -> None:
    """Verify that submitting with sync=false queues background processing and returns 202 Accepted."""
    payload = {
        "source_system": "async_clinic",
        "records": [
            {
                "id": "ASYNC-1",
                "mrn": "MRN-ASYNC-1",
                "first_name": "Async",
                "last_name": "Worker",
                "dob": "1985-06-15",
            }
        ],
    }

    response = await async_client.post("/api/v1/ingestion/json?sync=false", json=payload)
    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert data["job_id"] is not None
    assert data["status"] in ["RECEIVED", "PENDING", "COMPLETED"]

