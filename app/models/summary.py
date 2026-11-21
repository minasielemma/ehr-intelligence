"""SQLAlchemy ORM model for AI-generated clinical summaries and caching."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


def generate_uuid() -> str:
    """Generate string representation of a random UUID4."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class ClinicalSummaryModel(Base):
    """Persisted AI clinical summary records and intelligent inference cache."""

    __tablename__ = "clinical_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bundle_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1.0.0")
    temperature: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED", index=True)
    summary_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    clinical_summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_level: Mapped[str] = mapped_column(String(16), nullable=False, default="high")

    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    patient: Mapped["PatientModel"] = relationship("PatientModel")

    __table_args__ = (
        Index("ix_clinical_summary_patient_created", "patient_id", "created_at"),
        Index("ix_clinical_summary_hash_model", "bundle_hash", "model_name"),
    )
