"""Pydantic v2 schemas for Clinical Summarization, Output Validation, and Provider Health.

Enforces strict compliance with the clinical summary output specification, including
word-count constraints (< 200 words), confidence levels, diagnostic records categorization,
disclaimer preservation, and source reference traceability.
"""

from datetime import datetime, timezone
from enum import Enum
import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @model_validator(mode="before")
    @classmethod
    def coerce_confidence_score(cls, data: Any) -> Any:
        """Robustly coerce string, float, or partial dict into valid ConfidenceScore."""
        if isinstance(data, str):
            clean = data.lower().strip()
            level = ConfidenceLevel.MODERATE
            if "high" in clean:
                level = ConfidenceLevel.HIGH
            elif "low" in clean:
                level = ConfidenceLevel.LOW
            elif "mod" in clean:
                level = ConfidenceLevel.MODERATE
            return {
                "level": level,
                "explanation": f"Clinical confidence evaluated as {level.value} based on available evidence.",
            }
        if isinstance(data, (int, float)):
            level = ConfidenceLevel.HIGH if data >= 0.8 else (ConfidenceLevel.MODERATE if data >= 0.5 else ConfidenceLevel.LOW)
            return {
                "level": level,
                "explanation": f"Numerical confidence score {data} mapped to {level.value} tier.",
            }
        if isinstance(data, dict):
            if "level" in data and not data.get("explanation"):
                data["explanation"] = f"Clinical confidence evaluated as {data['level']} from patient records."
            elif "level" not in data:
                data["level"] = ConfidenceLevel.MODERATE
                data["explanation"] = "Confidence inferred from available clinical records."
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_llm_fields(cls, data: Any) -> Any:
        """Defensively normalize and coerce LLM output dictionaries to handle minor model defects."""
        if not isinstance(data, dict):
            return data

        # 1. Unwrap nested wrappers if the LLM placed output inside a sub-key
        for wrapper_key in ("clinical_summary_response", "summary_response", "clinical_summary", "response", "output", "data"):
            if wrapper_key in data and isinstance(data[wrapper_key], dict) and ("clinical_summary" in data[wrapper_key] or "summary" in data[wrapper_key]):
                merged = {**data[wrapper_key], **{k: v for k, v in data.items() if k != wrapper_key}}
                data = merged
                break

        # 2. Field aliases for clinical_summary (only when not explicitly provided)
        if "clinical_summary" not in data or data.get("clinical_summary") is None:
            for alias in ("summary", "narrative", "clinical_narrative", "overview", "clinical_overview", "text", "content", "patient_summary", "note"):
                if data.get(alias) and isinstance(data[alias], str) and data[alias].strip():
                    data["clinical_summary"] = data[alias].strip()
                    break

        # 2b. Clean serialized JSON artifacts if present in clinical_summary
        if data.get("clinical_summary") and isinstance(data["clinical_summary"], str):
            clean_str = data["clinical_summary"].strip()
            if clean_str.startswith("{") and clean_str.endswith("}"):
                try:
                    parsed = json.loads(clean_str)
                    clean_str = parsed.get("clinical_summary") or parsed.get("summary") or parsed.get("narrative") or clean_str
                    data["clinical_summary"] = clean_str
                except Exception:
                    pass

        # 2c. Clean XML tags, <untrusted_clinical_note>, and HTML tags from clinical_summary
        if data.get("clinical_summary") and isinstance(data["clinical_summary"], str):
            clean_str = data["clinical_summary"]
            if "<untrusted_clinical_note" in clean_str or "</untrusted_clinical_note>" in clean_str:
                clean_str = re.sub(r"</?untrusted_clinical_note[^>]*>", "", clean_str)
            if "<br" in clean_str:
                clean_str = re.sub(r"<br\s*/?>", "\n", clean_str)
            if "<" in clean_str and ">" in clean_str:
                clean_str = re.sub(r"<[^>]+>", "", clean_str)
            clean_str = re.sub(r"^[<«‹\s]+", "", clean_str)
            clean_str = re.sub(r"[>»›\s]+$", "", clean_str).strip()

            # Clean raw ingestion header prefixes without fabricating clinical ward assignments
            clean_str = re.sub(r"(?:Bed assignment id|Admission id|History id):\s*[\w\-]+[;,]?\s*", "", clean_str, flags=re.IGNORECASE).strip()

            data["clinical_summary"] = clean_str

        # 3. Field aliases for key_diagnoses
        if not data.get("key_diagnoses"):
            for alias in ("diagnoses", "conditions", "diagnosis_list", "key_conditions", "active_diagnoses"):
                if isinstance(data.get(alias), list):
                    data["key_diagnoses"] = [str(x) for x in data[alias]]
                    break

        # 4. Field aliases for flagged_anomalies
        if not data.get("flagged_anomalies"):
            for alias in ("anomalies", "abnormalities", "critical_findings", "abnormal_values", "alerts"):
                if isinstance(data.get(alias), list):
                    data["flagged_anomalies"] = [str(x) for x in data[alias]]
                    break

        # 5. Field aliases for chief_concern
        if not data.get("chief_concern"):
            for alias in ("chief_complaint", "presenting_complaint", "reason_for_visit", "complaint", "reason"):
                if data.get(alias) and isinstance(data[alias], str):
                    data["chief_concern"] = data[alias].strip()
                    break

        # 6. Ensure default disclaimer is populated if absent
        if not data.get("disclaimer"):
            data["disclaimer"] = DEFAULT_CLINICAL_DISCLAIMER

        return data

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

