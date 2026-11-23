# EHR Intelligence Platform

An enterprise-grade, AI-powered Electronic Health Record (EHR) Intelligence Platform that ingests heterogeneous, unstructured clinical media records, normalizes them to HL7 FHIR R4, generates evidence-grounded clinical summaries with LLMs, and surfaces a sub-second semantic search interface for clinicians.

> **Assessment Submission**: AI Full-Stack Candidate Assessment  
> **Documentation**: For design decisions, clinical research, and quality validation methodology, see [WRITEUP.md](WRITEUP.md).

---

## 1. Problem Statement

Clinical staff using Epic EHR spend significant time manually reviewing unstructured patient media records — lab PDFs, imaging notes, discharge summaries, and scanned documents — that live outside structured fields.

This platform automates this workflow end-to-end:
1. **Ingestion & Data Cleaning**: Parses messy JSON, CSV, and plain-text medical records, cleans OCR noise and inconsistent dates, resolves patient identity conflicts, and outputs a canonical intermediate representation with field-level audit provenance.
2. **HL7 FHIR R4 Normalization**: Maps cleaned clinical records to standard FHIR R4 resources (`Patient`, `DocumentReference`, `DiagnosticReport`, `Observation`, `Encounter`, `Condition`), validates them using official `fhir.resources` schemas, builds referentially linked Bundles, and stores them in SQLite and atomic POSIX files.
3. **AI-Powered Clinical Summarization**: Synthesizes longitudinal patient records into structured clinical summaries (< 200 words) using Anthropic Claude, OpenAI, or local Ollama with two-tier evidence validation, deterministic SHA-256 caching, and clinical disclaimers.
4. **Semantic Search Engine**: Generates dense 384-dimensional vector embeddings with `sentence-transformers/all-MiniLM-L6-v2`, indexes them in persistent ChromaDB collections with cosine distance indexing, and exposes a high-performance `POST /search` endpoint with native pre-filtering.
5. **Clinician Web Interface**: Provides a responsive, accessible Tailwind CSS interface featuring real-time debounced search, relevance indicators, and an interactive patient detail drawer with linked FHIR resource graph exploration.

---

## 2. Architecture & Design Decisions

The platform follows a **Modular Monolith** architecture, balancing strict domain boundaries with high transactional integrity and low operational overhead.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Clinician Web Interface                         │
│       Tailwind CSS • Vanilla JS ES Modules • Nginx Dev Container       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST (Port 8000 / 3001)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   FastAPI Modular Monolith (app/)                      │
│ ┌───────────────┐ ┌────────────────┐ ┌───────────────┐ ┌─────────────┐ │
│ │  Ingestion    │ │   FHIR R4      │ │   AI Clinical │ │  Semantic   │ │
│ │  Engine       │─┼─▶ Normalization│─┼─▶ Summarizer  │─┼─▶ Search    │ │
│ │  (Parsers,    │ │   (Mapper,     │ │   (Providers, │ │  (MiniLM,   │ │
│ │   Cleaners,   │ │    Validator,  │ │    Prompts,   │ │   ChromaDB, │ │
│ │   Normalizers)│ │    Bundler)    │ │    Evidence)  │ │   Filters)  │ │
│ └───────────────┘ └────────────────┘ └───────────────┘ └─────────────┘ │
└───────────────────┬──────────────────────────────────┬─────────────────┘
                    │                                  │
                    ▼                                  ▼
┌───────────────────────────────────────┐ ┌──────────────────────────────┐
│          Structured Storage           │ │      ChromaDB Vector DB      │
│  - SQLite (ehr.db via aiosqlite)      │ │  - Collection: ehr_records   │
│  - POSIX FHIR Bundles (0o600 / 0o700) │ │  - HNSW Cosine Index         │
└───────────────────────────────────────┘ └──────────────────────────────┘
```

### Key Architectural Decisions
- **Modular Monolith vs. Microservices**: Healthcare ingestion requires atomic database transactions and low-latency internal domain coordination. A modular monolith provides clean domain separation without distributed 2PC/Saga complexity.
- **Local-First & Multi-Provider AI Architecture**: Supports local Ollama models (`artifish/llama3.2-uncensored`, `llama3.1:8b`, `gemma3:12b`) for zero PHI exfiltration alongside cloud APIs (Claude 3.5 Sonnet, OpenAI GPT-4o).
- **Dual-Layer Persistence**: SQLite manages indexed metadata, jobs, and audits; POSIX storage stores immutable, validated raw FHIR R4 Bundles.
- **Deterministic Canonical Caching**: Summaries are cached in SQLite keyed by `SHA256(patient_id + bundle_hash + prompt_version + model_config)`, guaranteeing zero redundant inference costs on identical records.
- **Native Vector Pre-Filtering**: Date range and resource type filters are applied directly inside ChromaDB HNSW queries rather than post-filtered in Python.

---

## 3. Technology Stack

### Backend
- **Python 3.11+**
- **FastAPI**: Asynchronous REST API framework
- **Pydantic v2**: Request/response validation and settings management
- **fhir.resources (R4B)**: Official FHIR R4 schema models and validation
- **sentence-transformers (`all-MiniLM-L6-v2`)**: Dense clinical vector embeddings (384 dimensions)
- **ChromaDB (v0.5.23)**: Persistent vector database with cosine distance indexing
- **SQLite / SQLAlchemy / aiosqlite**: Relational persistence and Alembic migrations
- **pytest & pytest-asyncio**: Comprehensive test suite (207 tests)

### Frontend
- **Tailwind CSS**: Modern utility-first styling with custom clinical color palette
- **Vanilla JS (ES Modules)**: Native browser modules without heavy build toolchain overhead
- **Nginx (Alpine)**: Fast reverse-proxy serving UI assets and routing API requests
- **Fetch API**: Modern asynchronous HTTP communication with `AbortController` cancellation

---

## 4. Quickstart & Setup Instructions

### Option A: Running with Docker Compose (Recommended)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/minasielemma/ehr-intelligence.git
   cd ehr-intelligence
   ```

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env to add your ANTHROPIC_API_KEY or OPENAI_API_KEY if testing cloud LLMs
   ```

3. **Start all services**:
   ```bash
   docker compose up -d --build
   ```

4. **Verify running containers**:
   ```bash
   docker compose ps
   ```
   - **Backend API**: `http://localhost:8000` (Docs: `http://localhost:8000/api/v1/docs`)
   - **Frontend UI**: `http://localhost:3001`
   - **ChromaDB**: `http://localhost:8001`

---

### Option B: Running Locally (Native Python 3.11+)

1. **Create and activate a virtual environment**:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize the SQLite database**:
   ```bash
   alembic upgrade head
   ```

4. **Start the backend server**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Serve the frontend**:
   ```bash
   cd frontend && python3 -m http.server 3000
   ```

---

## 5. Task-by-Task Implementation Details

### Task 1: Heterogeneous Data Ingestion & Cleaning
- **Multi-Format Parsers** (`app/ingestion/parsers/`): Supports JSON (simulated EHR export), CSV (lab results), plain text (scanned notes), native FHIR R4 JSON, and ZIP packages.
- **Clinical Data Cleaners** (`app/ingestion/cleaners/`): Normalizes Unicode, removes OCR noise and HTML/XML tags, and preserves clinical abbreviations.
- **Robust Normalizers** (`app/ingestion/normalizers/`):
  - `date_normalizer.py`: Handles 15+ date formats (ISO 8601, US/UK dates, timestamps); detects and flags ambiguous dates (e.g. `04/05/2012`).
  - `gender_normalizer.py`: Maps disparate source gender strings to HL7 FHIR codes (`male`, `female`, `other`, `unknown`).
  - `mrn_normalizer.py`: Standardizes patient medical record numbers.
  - `patient_matcher.py`: Reconciles duplicate records and conflicting patient IDs using probabilistic matching.
- **Audit Logging**: Emits an `AuditRecord` for every field transformation with before/after values and reasoning.

### Task 2: HL7 FHIR R4 Normalization
- **Resource Mapping** (`app/fhir/mapper.py`): Maps canonical records to `Patient`, `DocumentReference`, `DiagnosticReport`, `Observation`, `Encounter`, and `Condition`.
- **Strict Schema Validation** (`app/fhir/validator.py`): Validates generated resources against official `fhir.resources.R4B` models and outputs structured `FHIRValidationReport` instances.
- **Referential Integrity** (`app/fhir/bundler.py`): Generates valid FHIR Bundles using UUID URNs (`urn:uuid:...`) ensuring all resources reference the parent `Patient` and `Encounter`.
- **Dual-Layer Persistence** (`app/fhir/storage.py`): Atomically saves bundles to disk with POSIX permissions `0o600` and records references in SQLite.

### Task 3: AI-Powered Clinical Summarization
- **Multi-Provider LLM Engine** (`app/ai/providers/`): Supports Anthropic Claude, OpenAI, and local Ollama with unified async HTTP client pooling.
- **Clinical Prompt Engineering** (`app/ai/prompts/`): Safely isolates untrusted clinical notes inside `<untrusted_clinical_note>` tags to prevent prompt injection. Enforces a strict **< 200 words** narrative limit.
- **Schema Validation** (`app/schemas/summary.py`): Output includes:
  - `chief_concern`: Presenting clinical complaint.
  - `key_diagnoses`: Confirmed diagnoses list.
  - `recent_diagnostic_records`: Categorized into `laboratory`, `imaging`, and `other`.
  - `flagged_anomalies`: Critical values and out-of-range observations.
  - `confidence`: Confidence score with clinical rationale.
  - `disclaimer`: Standard AI decision-support disclaimer.
- **Two-Tier Evidence Grounding** (`app/ai/validator.py`): Verifies generated claims against source FHIR resources; unverifiable assertions trigger automatic confidence downgrading.
- **Deterministic Canonical Caching** (`app/ai/cache.py`): SQLite cache keyed by `SHA256(patient_id + bundle_hash + prompt_version + model_config)` prevents redundant API calls and protects against thundering herds.

### Task 4: Vector Semantic Search
- **Embedding Generation** (`app/search/embeddings.py`): Embeds documents and queries with `sentence-transformers/all-MiniLM-L6-v2` into dense 384-dimensional vectors.
- **Vector Store** (`app/search/vector_store.py`): Persists vectors in ChromaDB with cosine distance indexing and idempotent chunk IDs (`{record_id}:{source}:{chunk_index}`).
- **Endpoint**: `POST /search` (and `POST /api/v1/search`) accepts free-text clinical queries and returns top-ranked results with cosine similarity scores in [0, 1].
- **Filtering**: Native ChromaDB pre-filtering on `resource_type`, `date_from`, and `date_to`.
- **Performance**: Returns results in **< 50 milliseconds** (well under the 2-second SLA).

### Task 5: Frontend Search & Summary UI
- **Real-Time Search Bar**: Debounced input (350ms) with `AbortController` cancellation to discard obsolete in-flight requests. Keyboard shortcut (`/`) focuses the search bar.
- **Result Cards**: Displays patient name/MRN, record timestamp, resource type badge, relevance score bar, and clinical snippet.
- **Patient Detail Drawer**: Slide-out drawer displaying full patient profile, AI clinical summary with confidence badge, linked FHIR resource explorer, and manual regeneration triggers.
- **Filter Controls**: Dropdowns for FHIR resource type (`Observation`, `Condition`, `DiagnosticReport`, etc.) and date range picker.
- **Accessibility**: Semantic HTML, ARIA labels, focus states, and keyboard navigation.

---

## 6. API Usage & Examples

### Semantic Search: `POST /search`

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key" \
  -d '{
    "query": "high blood sugar and uncontrolled diabetes"
  }'
```

#### Sample Response:
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

#### Filtered Search:
```bash
# Filter by resource type and date range
curl -X POST "http://localhost:8000/search?resource_type=DiagnosticReport&date_from=2024-01-01&date_to=2024-12-31" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-test-key" \
  -d '{"query": "echocardiogram"}'
```

### Vector Index Backfill CLI

To backfill embeddings for all existing stored FHIR bundles and AI summaries:
```bash
# In Docker
docker exec ehr-backend python -m app.scripts.reindex_embeddings --reset

# Local Environment
python -m app.scripts.reindex_embeddings --reset --batch-size 32
```

---

## 7. Running Tests

The test suite covers unit, integration, security, and performance verification:

```bash
# Run entire test suite inside Docker:
docker exec ehr-backend pytest -v

# Run specific domain test suites:
docker exec ehr-backend pytest tests/unit/test_normalization.py -v
docker exec ehr-backend pytest tests/unit/test_fhir_validation.py -v
docker exec ehr-backend pytest tests/integration/test_ai_clinical_accuracy_cases.py -v
docker exec ehr-backend pytest tests/integration/test_semantic_search.py -v
```

**Test Results**: **207 passed**, 0 failures, 100% pass rate.
