"""Health check endpoint reporting application and infrastructure dependency status."""

import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, status
import httpx
from sqlalchemy import text

from app import __version__
from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.models.database import get_engine
from app.schemas.health import HealthResponse, ServiceStatus

router = APIRouter()


async def check_database_status(db_url: str, database_path: str) -> ServiceStatus:
    """Verify SQLite storage path, permissions, and active database connectivity."""
    try:
        path = Path(database_path)
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)

        engine = get_engine(db_url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        return ServiceStatus(
            status="healthy",
            details={
                "path": str(path),
                "directory_exists": directory.exists(),
                "connected": True,
            },
        )
    except Exception as exc:
        return ServiceStatus(
            status="unreachable",
            details={"path": database_path, "error": str(exc)},
        )


async def check_vector_store_status(chroma_url: str) -> ServiceStatus:
    """Check connectivity to containerized ChromaDB instance."""
    heartbeat_urls = [
        f"{chroma_url}/api/v1/heartbeat",
        f"{chroma_url}/api/v2/heartbeat",
        f"{chroma_url}/api/heartbeat",
    ]
    last_error = None

    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in heartbeat_urls:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return ServiceStatus(
                        status="healthy",
                        details={
                            "url": chroma_url,
                            "endpoint": url,
                            "response": response.json(),
                        },
                    )
            except Exception as exc:
                last_error = str(exc)

    return ServiceStatus(
        status="unreachable",
        details={
            "url": chroma_url,
            "error": last_error or "Unable to connect to ChromaDB heartbeat endpoint",
        },
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Platform Health Check",
    description="Reports the operational status of the backend API and connected infrastructure dependencies.",
)
async def get_health(settings: Settings = Depends(get_current_settings)) -> HealthResponse:
    """Perform health checks on infrastructure services and return overall status."""
    db_status = await check_database_status(settings.sqlite_url, settings.DATABASE_PATH)
    vector_status = await check_vector_store_status(settings.chroma_url)

    # Determine composite platform health
    is_healthy = db_status.status == "healthy" and vector_status.status == "healthy"
    overall_status = "healthy" if is_healthy else "degraded"

    return HealthResponse(
        status=overall_status,
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        version=__version__,
        timestamp=datetime.now(timezone.utc),
        services={
            "database": db_status,
            "vector_store": vector_status,
        },
    )
