"""Health check and dependency status schemas."""

from datetime import datetime
from typing import Any, Dict
from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    """Status details for an individual infrastructure service."""

    status: str = Field(..., description="Operational status: healthy, available, unreachable, degraded")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional context or diagnostics")


class HealthResponse(BaseModel):
    """Overall system health and infrastructure dependencies response."""

    status: str = Field(..., description="Overall platform status: healthy or degraded")
    app_name: str = Field(..., description="Name of the application")
    environment: str = Field(..., description="Active runtime environment")
    version: str = Field(..., description="Application version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of the health check")
    services: Dict[str, ServiceStatus] = Field(
        default_factory=dict,
        description="Health and connectivity state of infrastructure components",
    )
