# EHR Intelligence Platform

AI-powered Electronic Health Record (EHR) Intelligence Platform featuring HL7 FHIR R4 normalization, evidence-grounded clinical summarization, and vector-accelerated clinical semantic search.

---

## Semantic Search Feature

The Semantic Search engine enables clinicians to query across all patient records and AI-generated clinical summaries using natural language. It embeds queries and clinical documents with `sentence-transformers/all-MiniLM-L6-v2` into dense 384-dimensional normalized vectors, stored and queried in persistent ChromaDB collections with cosine distance indexing.

### 1. Vector Embeddings Backfill CLI

A management script is provided to backfill dense embeddings for all existing stored FHIR bundles and AI summaries:

```bash
# Run inside the Docker backend container or in local environment:
python -m app.scripts.reindex_embeddings

# Optional flags:
# --reset: Wipe existing vector store collection before backfilling
# --batch-size N: Batch size for model inference (default: 32)
python -m app.scripts.reindex_embeddings --reset --batch-size 32
```

In Docker:
```bash
docker exec ehr-backend python -m app.scripts.reindex_embeddings --reset
```

The indexing process runs in batches of 32–64, logs progress, extracts clinical narrative text from all FHIR entries and AI summaries, splits long documents into overlapping token chunks, and persists them idempotently using deterministic IDs (`{record_id}:{source}:{chunk_index}`).

### 2. Live Synchronization

The vector index automatically stays in sync with platform operations:
- When new FHIR bundles are normalized and saved (`FHIRNormalizationService.normalize_patient_bundle()`), vector indexing is scheduled in a background task.
- When new AI clinical summaries are generated and cached (`SummaryCacheManager.put_cached_summary()`), the summary is automatically indexed in the background.
- When a patient's summary cache is invalidated (`DELETE /api/v1/ai/cache/{patient_id}`), all corresponding summary vectors are pruned in the background.
- Background tasks prevent vector computations from blocking write paths.

### 3. API Usage: `POST /search`

The endpoint is accessible at `POST /search` (and `POST /api/v1/search`):

#### Curl Example
```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key" \
  -d '{
    "query": "high blood sugar and uncontrolled diabetes"
  }'
```

#### Sample Response
```json
{
  "query": "high blood sugar and uncontrolled diabetes",
  "count": 2,
  "took_ms": 48.6,
  "results": [
    {
      "record_id": "obs-glucose-001",
      "patient_id": "pat-001",
      "resource_type": "Observation",
      "source": "fhir_document",
      "date": "2024-05-01T10:00:00Z",
      "score": 0.885,
      "snippet": "Observation: Glucose [Mass/volume] in Blood | Value: 215 mg/dL | Severe hyperglycemia with elevated fasting blood sugar levels."
    },
    {
      "record_id": "cond-dm2-002",
      "patient_id": "pat-001",
      "resource_type": "Condition",
      "source": "fhir_document",
      "date": "2024-04-15T09:00:00Z",
      "score": 0.812,
      "snippet": "Condition: Type 2 diabetes mellitus poorly controlled with insulin resistance and elevated HbA1c."
    }
  ]
}
```

### 4. Query Filtering

Filtering is executed natively within ChromaDB prior to nearest-neighbor retrieval (pre-filtering), avoiding wasteful Python post-filtering.

Supported query parameters:
- `resource_type` (string): Restrict search to specific FHIR resource types (e.g., `Observation`, `Condition`, `DiagnosticReport`, `DocumentReference`, `ClinicalSummary`).
- `date_from` (ISO 8601 string): Inclusive lower bound for record clinical dates (e.g., `2024-01-01T00:00:00Z` or `2024-01-01`).
- `date_to` (ISO 8601 string): Inclusive upper bound for record clinical dates (e.g., `2024-12-31T23:59:59Z` or `2024-12-31`).

#### Examples:
```bash
# Filter by resource type
curl -X POST "http://localhost:8000/search?resource_type=Observation" \
  -H "Content-Type: application/json" \
  -d '{"query": "elevated blood pressure"}'

# Filter by date range
curl -X POST "http://localhost:8000/search?date_from=2024-01-01T00:00:00Z&date_to=2024-06-30T23:59:59Z" \
  -H "Content-Type: application/json" \
  -d '{"query": "kidney function"}'

# Combined filters
curl -X POST "http://localhost:8000/search?resource_type=DiagnosticReport&date_from=2024-01-01&date_to=2024-12-31" \
  -H "Content-Type: application/json" \
  -d '{"query": "echocardiogram"}'
```

If `date_from > date_to` or the query string is empty/whitespace, HTTP 422 Unprocessable Entity is returned.

### 5. Running Tests

```bash
# Run entire test suite (unit + integration):
docker exec ehr-backend pytest -v

# Run semantic search tests specifically:
docker exec ehr-backend pytest tests/unit/test_search.py tests/integration/test_semantic_search.py -v
```
