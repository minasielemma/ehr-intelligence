"""Pydantic v2 schemas for Clinical Summarization, Output Validation, and Provider Health.

Enforces strict compliance with the clinical summary output specification, including
word-count constraints (< 200 words), confidence levels, diagnostic records categorization,
disclaimer preservation, and source reference traceability.
"""

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfidenceLevel(str, Enum):
    """Clinical confidence assessment level for generated summaries."""
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class ConfidenceScore(BaseModel):
    """Confidence assessment with clinical justification."""
    model_config = ConfigDict(extra="ignore")

    level: ConfidenceLevel = Field(
        ...,
        description="Confidence level: high, moderate, or low based on source data quality and grounding",
    )
    explanation: str = Field(
        ...,
        description="Clinical rationale explaining the assigned confidence level and any evidential limitations",
    )


class DiagnosticRecordsSummary(BaseModel):
    """Categorized summary of recent diagnostic findings extracted from FHIR records."""
    model_config = ConfigDict(extra="ignore")

    laboratory: List[str] = Field(
        default_factory=list,
        description="Key laboratory observations and panel results with numerical values, units, and interpretation",
    )
    imaging: List[str] = Field(
        default_factory=list,
        description="Key imaging studies, modalities, and documented radiological impressions",
    )
    other: List[str] = Field(
        default_factory=list,
        description="Other diagnostic procedures, vital sign evaluations, or physiological measurements",
    )


class ModelMetadata(BaseModel):
    """Provenance metadata regarding the LLM provider and model used for inference."""
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(..., description="Active LLM provider identifier (e.g. ollama, anthropic, openai)")
    model: str = Field(..., description="Exact model name or checkpoint used (e.g. gemma3:12b, llama3.1:8b)")


DEFAULT_CLINICAL_DISCLAIMER = "AI-generated summary. Not a clinical diagnosis or medical decision."


def count_words(text: str) -> int:
    """Accurately count words in clinical summary text."""
    if not text:
        return 0
    return len(re.findall(r"\b\w+(?:['\-]\w+)*\b", text.strip()))


class ClinicalSummaryResponse(BaseModel):
    """Strict schema for AI-generated clinical summaries matching Section 5 requirements."""
    model_config = ConfigDict(extra="ignore")

    patient_id: str = Field(..., description="Unique patient identifier")
    chief_concern: Optional[str] = Field(
        default=None,
        description="Primary presenting complaint, chief concern, or clinical rationale for care",
    )
    key_diagnoses: List[str] = Field(
        default_factory=list,
        description="Active, confirmed, or suspected diagnoses extracted strictly from source records",
    )
    recent_diagnostic_records: DiagnosticRecordsSummary = Field(
        default_factory=DiagnosticRecordsSummary,
        description="Categorized diagnostic results (laboratory, imaging, other)",
    )
    flagged_anomalies: List[str] = Field(
        default_factory=list,
        description="Explicitly documented abnormalities, critical lab values, or conflicting findings",
    )
    clinical_summary: str = Field(
        ...,
        description="Concise, synthesized narrative clinical summary (strictly fewer than 200 words)",
    )
    confidence: ConfidenceScore = Field(
        ...,
        description="Clinical confidence level and explanation",
    )
    disclaimer: str = Field(
        default=DEFAULT_CLINICAL_DISCLAIMER,
        description="Standard medical disclaimer",
    )
    source_references: List[str] = Field(
        default_factory=list,
        description="Traceable list of underlying FHIR resource references (e.g. Observation/obs-01, Condition/c-02)",
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp of summary generation",
    )
    model_metadata: ModelMetadata = Field(
        ...,
        description="Metadata on the LLM provider and model execution",
    )

    @field_validator("clinical_summary")
    @classmethod
    def validate_clinical_summary_word_count(cls, v: str) -> str:
        """Enforce strict constraint: final clinical summary text must contain fewer than 200 words."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Clinical summary narrative must not be empty")
        words = count_words(stripped)
        if words >= 200:
            raise ValueError(
                f"Clinical summary text must contain fewer than 200 words (measured {words} words)"
            )
        return stripped

    @property
    def word_count(self) -> int:
        """Return the word count of the narrative summary."""
        return count_words(self.clinical_summary)


# ==============================================================================
# API Request & Batch Response Schemas
# ==============================================================================

class SummarizeBundleRequest(BaseModel):
    """Request payload to summarize a provided FHIR R4 Bundle directly."""
    model_config = ConfigDict(extra="ignore")

    bundle: Dict[str, Any] = Field(..., description="HL7 FHIR R4 Bundle JSON payload")
    force_refresh: bool = Field(
        default=False,
        description="Bypass cached summary and force re-inference if True",
    )


class SummarizePatientRequest(BaseModel):
    """Request payload to summarize a persisted database patient's records."""
    model_config = ConfigDict(extra="ignore")

    patient_id: str = Field(..., description="Unique patient identifier")
    bundle_id: Optional[str] = Field(
        default=None,
        description="Specific bundle ID to summarize; if omitted, the latest bundle is used",
    )
    force_refresh: bool = Field(
        default=False,
        description="Bypass cached summary and force re-inference if True",
    )


class BatchSummarizeRequest(BaseModel):
    """Request payload to summarize multiple patients in a batch."""
    model_config = ConfigDict(extra="ignore")

    patient_ids: List[str] = Field(
        ...,
        min_length=1,
        description="List of patient IDs to summarize sequentially/concurrently with isolation",
    )
    force_refresh: bool = Field(
        default=False,
        description="Bypass cache for all requested patients if True",
    )


class SummaryExecutionStatus(str, Enum):
    """Status classification for summary generation."""
    SUCCESS = "SUCCESS"
    CACHE_HIT = "CACHE_HIT"
    FAILED = "FAILED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PatientSummaryItem(BaseModel):
    """Summary result item for a single patient within a batch or individual request."""
    model_config = ConfigDict(extra="ignore")

    patient_id: str = Field(..., description="Patient identifier")
    status: SummaryExecutionStatus = Field(..., description="Execution outcome status")
    summary: Optional[ClinicalSummaryResponse] = Field(default=None, description="The validated clinical summary")
    error_message: Optional[str] = Field(default=None, description="Error details if processing failed")
    cached: bool = Field(default=False, description="True if retrieved from persistent cache without re-inference")
    execution_time_ms: float = Field(default=0.0, description="Latency in milliseconds")


class BatchSummarizeResponse(BaseModel):
    """Consolidated response payload for batch summarization jobs."""
    model_config = ConfigDict(extra="ignore")

    total_patients: int = Field(..., description="Total patients requested")
    successful_count: int = Field(..., description="Count of successfully generated summaries")
    failed_count: int = Field(..., description="Count of failed patient summaries")
    cache_hit_count: int = Field(..., description="Count of summaries served from cache")
    results: List[PatientSummaryItem] = Field(default_factory=list, description="Per-patient summary outcomes")
    completed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp of batch job completion",
    )


class LLMHealthResponse(BaseModel):
    """Health check status and connectivity report for the active LLM provider."""
    model_config = ConfigDict(extra="ignore")

    status: str = Field(..., description="Overall status: healthy or degraded/unreachable")
    provider: str = Field(..., description="Active provider: ollama, anthropic, openai")
    model: str = Field(..., description="Target model name")
    available: bool = Field(..., description="True if provider endpoint and model are ready")
    latency_ms: Optional[float] = Field(default=None, description="Round-trip ping/tags latency in milliseconds")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Underlying provider metadata or errors")


class SummaryTaskResponse(BaseModel):
    """Status and result response for asynchronous AI clinical summary generation and regeneration."""
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(..., description="Unique background task identifier")
    patient_id: str = Field(..., description="Target patient identifier")
    status: str = Field(..., description="Task execution status: PENDING, PROCESSING, COMPLETED, FAILED, or NOT_FOUND")
    message: str = Field(..., description="Human-readable status summary")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO-8601 timestamp of task creation",
    )
    started_at: Optional[datetime] = Field(default=None, description="ISO-8601 timestamp of execution start")
    completed_at: Optional[datetime] = Field(default=None, description="ISO-8601 timestamp of task completion")
    duration_seconds: Optional[float] = Field(default=None, description="Elapsed execution duration in seconds")
    summary: Optional[ClinicalSummaryResponse] = Field(default=None, description="Generated clinical summary object when completed")
    error_message: Optional[str] = Field(default=None, description="Detailed error description if task failed")

