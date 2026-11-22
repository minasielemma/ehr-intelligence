"""Pydantic schemas for semantic search queries, filters, and responses."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    """Semantic search request payload."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language clinical search query",
        examples=["patient with uncontrolled diabetes and elevated HbA1c"],
    )
    patient_id: Optional[str] = Field(
        None,
        description="Optional patient identifier to scope the search to a single patient's records",
        examples=["pat-12345"],
    )
    resource_type: Optional[str] = Field(
        None,
        description="Optional FHIR resourceType filter (e.g. Observation, Condition, DiagnosticReport)",
        examples=["Observation"],
    )
    date_from: Optional[str] = Field(
        None,
        description="Optional inclusive start date/timestamp in ISO 8601 format",
        examples=["2024-01-01T00:00:00Z"],
    )
    date_to: Optional[str] = Field(
        None,
        description="Optional inclusive end date/timestamp in ISO 8601 format",
        examples=["2024-12-31T23:59:59Z"],
    )
    top_k: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Optional maximum number of distinct records to return",
        examples=[5],
    )

    @field_validator("query")
    @classmethod
    def validate_non_empty_query(cls, v: str) -> str:
        """Ensure search query is not purely whitespace."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Query string cannot be empty or purely whitespace.")
        return stripped


class SearchResultItem(BaseModel):
    """Individual clinical record match from semantic search."""

    record_id: str = Field(..., description="Unique record or FHIR resource identifier")
    patient_id: str = Field(..., description="Patient identifier the record belongs to")
    resource_type: str = Field(
        ...,
        description="FHIR resourceType (e.g. Observation, Condition, DiagnosticReport) or ClinicalSummary",
    )
    source: Literal["fhir_document", "ai_summary"] = Field(
        ...,
        description="Origin of the indexed document: 'fhir_document' or 'ai_summary'",
    )
    date: str = Field(..., description="ISO 8601 formatted record date/timestamp (UTC)")
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Cosine relevance similarity score in [0, 1] where 1.0 is highest match",
    )
    snippet: str = Field(..., description="Contextual preview text snippet of the matched content")


class SearchResponse(BaseModel):
    """Semantic search response containing ranked, distinct clinical record matches."""

    query: str = Field(..., description="The original natural language search query")
    count: int = Field(..., ge=0, description="Number of distinct record results returned")
    took_ms: float = Field(..., ge=0.0, description="Query processing latency in milliseconds")
    results: List[SearchResultItem] = Field(
        default_factory=list,
        description="Ranked list of top distinct patient record matches",
    )
