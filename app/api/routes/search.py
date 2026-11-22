"""FastAPI router for clinical semantic search across FHIR documents and AI summaries."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_current_settings
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.schemas.search import SearchRequest, SearchResponse
from app.search.retrieval import SemanticSearchService

logger = get_logger(__name__)

router = APIRouter(
    tags=["Semantic Search"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Semantic Search Across Patient Clinical Records",
    description=(
        "Executes natural language semantic search across normalized FHIR clinical resources "
        "and AI-generated clinical summaries. Embeds the query using Sentence Transformers, "
        "applies metadata pre-filtering (FHIR resource type and date ranges), and returns the "
        "top distinct patient records ranked by cosine relevance score in [0, 1]."
    ),
    responses={
        200: {
            "description": "Successfully retrieved top matching clinical records.",
            "content": {
                "application/json": {
                    "example": {
                        "query": "patient with high blood sugar and HbA1c",
                        "count": 1,
                        "took_ms": 42.5,
                        "results": [
                            {
                                "record_id": "obs-glucose-001",
                                "patient_id": "pat-12345",
                                "resource_type": "Observation",
                                "source": "fhir_document",
                                "date": "2024-05-01T10:00:00Z",
                                "score": 0.885,
                                "snippet": "Observation: Glucose [Mass/volume] in Blood | Value: 185 mg/dL | Interpretation: High",
                            }
                        ],
                    }
                }
            },
        },
        401: {"description": "Unauthorized: Missing or invalid X-API-Key header."},
        422: {"description": "Unprocessable Entity: Empty query string or invalid date range."},
    },
)
async def semantic_search_records(
    payload: SearchRequest,
    patient_id: Optional[str] = Query(
        None,
        description="Filter results to a specific patient identifier (e.g. pat-12345)",
        examples=["pat-12345"],
    ),
    resource_type: Optional[str] = Query(
        None,
        description="Filter results by FHIR resourceType (e.g. Observation, Condition, DiagnosticReport)",
        examples=["Observation"],
    ),
    date_from: Optional[str] = Query(
        None,
        description="Inclusive start date/timestamp in ISO 8601 format (e.g. '2024-01-01T00:00:00Z' or '2024-01-01')",
        examples=["2024-01-01T00:00:00Z"],
    ),
    date_to: Optional[str] = Query(
        None,
        description="Inclusive end date/timestamp in ISO 8601 format (e.g. '2024-12-31T23:59:59Z' or '2024-12-31')",
        examples=["2024-12-31T23:59:59Z"],
    ),
    top_k: Optional[int] = Query(
        None,
        ge=1,
        le=100,
        description="Maximum number of distinct records to return (default: from system settings)",
        examples=[5],
    ),
    settings: Settings = Depends(get_current_settings),
) -> SearchResponse:
    """Natural language query over all patient documents with ChromaDB pre-filtering."""
    service = SemanticSearchService(settings=settings)
    target_patient_id = patient_id or payload.patient_id
    target_resource_type = resource_type or payload.resource_type
    target_date_from = date_from or payload.date_from
    target_date_to = date_to or payload.date_to
    target_top_k = top_k if top_k is not None else payload.top_k
    return await service.search(
        query=payload.query,
        resource_type=target_resource_type,
        patient_id=target_patient_id,
        date_from=target_date_from,
        date_to=target_date_to,
        top_k=target_top_k,
    )
