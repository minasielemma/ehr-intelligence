"""Integration tests for POST /search semantic search endpoint with seeded dataset."""

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, List
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.search.embeddings import get_embedding_generator
from app.search.extraction import parse_datetime_to_timestamp
from app.search.vector_store import VectorRecord, VectorStore, get_vector_store


@pytest.fixture
async def seeded_vector_store(test_settings: Settings, isolate_vector_store: VectorStore) -> VectorStore:
    """Seed exactly 50 clinical records with diverse resource types and dates into isolated test vector store."""
    emb_gen = get_embedding_generator(test_settings.EMBEDDING_MODEL)

    # 50 diverse records across Observations, Conditions, DiagnosticReports, DocumentReferences, Summaries
    raw_records = [
        # Diabetes / Glucose group (Semantic targets)
        {
            "record_id": "obs-glucose-high",
            "patient_id": "pat-001",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2024-05-01T10:00:00Z",
            "text": "Observation: Glucose [Mass/volume] in Blood | Value: 215 mg/dL | Severe hyperglycemia with elevated fasting blood sugar levels.",
        },
        {
            "record_id": "cond-dm2-severe",
            "patient_id": "pat-001",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2024-04-15T09:00:00Z",
            "text": "Condition: Type 2 diabetes mellitus poorly controlled with insulin resistance and elevated HbA1c.",
        },
        {
            "record_id": "diag-a1c-report",
            "patient_id": "pat-002",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-05-10T14:30:00Z",
            "text": "DiagnosticReport: Hemoglobin A1c test | Conclusion: HbA1c is 9.2%, indicating chronic glycemic dysregulation.",
        },
        {
            "record_id": "summary-diabetic-keto",
            "patient_id": "pat-003",
            "resource_type": "ClinicalSummary",
            "source": "ai_summary",
            "date": "2024-05-02T16:00:00Z",
            "text": "ClinicalSummary: Patient admitted with diabetic ketoacidosis secondary to uncontrolled high blood glucose and missed insulin doses.",
        },
        {
            "record_id": "doc-endo-consult",
            "patient_id": "pat-004",
            "resource_type": "DocumentReference",
            "source": "fhir_document",
            "date": "2024-06-01T11:00:00Z",
            "text": "DocumentReference: Endocrinology Consultation Note: Persistent hyperglycemia post-prandial exceeding 240 mg/dL. Adjusting basal insulin.",
        },

        # Cardiology / Hypertension group
        {
            "record_id": "obs-bp-high",
            "patient_id": "pat-005",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2024-03-12T08:00:00Z",
            "text": "Observation: Blood Pressure systolic/diastolic | Value: 168/102 mmHg | Stage 2 hypertension.",
        },
        {
            "record_id": "cond-htn",
            "patient_id": "pat-005",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2023-11-20T10:00:00Z",
            "text": "Condition: Essential hypertension with hypertensive vascular disease.",
        },
        {
            "record_id": "diag-echo",
            "patient_id": "pat-006",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-02-14T11:30:00Z",
            "text": "DiagnosticReport: Transthoracic Echocardiogram | Conclusion: Left ventricular ejection fraction 55%, mild concentric hypertrophy.",
        },
        {
            "record_id": "summary-cardiac",
            "patient_id": "pat-006",
            "resource_type": "ClinicalSummary",
            "source": "ai_summary",
            "date": "2024-02-15T09:00:00Z",
            "text": "ClinicalSummary: 65-year-old male with long-standing essential hypertension and stable angina on Lisinopril and Metoprolol.",
        },
        {
            "record_id": "obs-cholesterol",
            "patient_id": "pat-007",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2023-08-10T10:00:00Z",
            "text": "Observation: Lipid panel Total Cholesterol | Value: 245 mg/dL | Interpretation: Borderline high hyperlipidemia.",
        },

        # Respiratory / Pulmonology group
        {
            "record_id": "cond-asthma",
            "patient_id": "pat-008",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2024-01-20T14:00:00Z",
            "text": "Condition: Moderate persistent bronchial asthma with acute bronchospasm and wheezing.",
        },
        {
            "record_id": "diag-chest-xray",
            "patient_id": "pat-008",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-01-21T09:15:00Z",
            "text": "DiagnosticReport: Chest X-ray 2 views | Conclusion: Clear lung fields, no focal consolidation, pneumothorax, or pleural effusion.",
        },
        {
            "record_id": "obs-spo2",
            "patient_id": "pat-009",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2024-07-04T12:00:00Z",
            "text": "Observation: Oxygen saturation in arterial blood SpO2 | Value: 94 % | Room air mild hypoxemia.",
        },
        {
            "record_id": "summary-copd",
            "patient_id": "pat-010",
            "resource_type": "ClinicalSummary",
            "source": "ai_summary",
            "date": "2024-07-05T15:00:00Z",
            "text": "ClinicalSummary: Chronic obstructive pulmonary disease (COPD) exacerbation treated with oral steroids and bronchodilator nebulizers.",
        },
        {
            "record_id": "doc-pulm-note",
            "patient_id": "pat-010",
            "resource_type": "DocumentReference",
            "source": "fhir_document",
            "date": "2024-07-06T11:00:00Z",
            "text": "DocumentReference: Pulmonary Clinic Progress Note: Demonstrates improved peak expiratory flow rate post-treatment.",
        },

        # Nephrology / Renal group
        {
            "record_id": "obs-creatinine",
            "patient_id": "pat-011",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2024-09-18T10:00:00Z",
            "text": "Observation: Serum Creatinine | Value: 1.8 mg/dL | Elevated indicative of decreased glomerular filtration.",
        },
        {
            "record_id": "cond-ckd",
            "patient_id": "pat-011",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2024-09-19T08:30:00Z",
            "text": "Condition: Chronic kidney disease stage 3b with moderate renal insufficiency and proteinuria.",
        },
        {
            "record_id": "diag-renal-us",
            "patient_id": "pat-012",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-10-02T13:00:00Z",
            "text": "DiagnosticReport: Renal Ultrasound Bilateral | Conclusion: Normal kidney size with bilateral increased cortical echogenicity.",
        },

        # Infectious disease group
        {
            "record_id": "obs-wbc",
            "patient_id": "pat-013",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2023-12-05T09:00:00Z",
            "text": "Observation: Leukocytes in Blood WBC count | Value: 14.5 10*3/uL | Leukocytosis consistent with active infection.",
        },
        {
            "record_id": "cond-uti",
            "patient_id": "pat-013",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2023-12-05T10:00:00Z",
            "text": "Condition: Acute cystitis and urinary tract infection with dysuria and frequency.",
        },
        {
            "record_id": "summary-uti",
            "patient_id": "pat-013",
            "resource_type": "ClinicalSummary",
            "source": "ai_summary",
            "date": "2023-12-06T11:00:00Z",
            "text": "ClinicalSummary: Female patient presenting with uncomplicated urinary tract infection responding well to nitrofurantoin.",
        },

        # Orthopedics / Musculoskeletal group
        {
            "record_id": "diag-ankle-xray",
            "patient_id": "pat-014",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-08-20T16:00:00Z",
            "text": "DiagnosticReport: Ankle Radiograph 3 Views | Conclusion: Nondisplaced fracture of distal lateral malleolus.",
        },
        {
            "record_id": "cond-osteoarthritis",
            "patient_id": "pat-015",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2023-05-15T10:00:00Z",
            "text": "Condition: Primary bilateral osteoarthritis of knee with chronic mechanical joint pain.",
        },
        {
            "record_id": "doc-ortho-note",
            "patient_id": "pat-015",
            "resource_type": "DocumentReference",
            "source": "fhir_document",
            "date": "2023-05-16T14:00:00Z",
            "text": "DocumentReference: Orthopedic Surgery Consultation: Recommended physical therapy and topical NSAIDs prior to consideration of arthroplasty.",
        },

        # Neurology group
        {
            "record_id": "cond-migraine",
            "patient_id": "pat-016",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2024-11-01T09:00:00Z",
            "text": "Condition: Chronic migraine without aura with photophobia and nausea.",
        },
        {
            "record_id": "diag-brain-mri",
            "patient_id": "pat-016",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-11-05T13:30:00Z",
            "text": "DiagnosticReport: MRI Brain with and without contrast | Conclusion: No evidence of acute intracranial hemorrhage or mass lesion.",
        },

        # Gastroenterology group
        {
            "record_id": "cond-gerd",
            "patient_id": "pat-017",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2023-03-10T11:00:00Z",
            "text": "Condition: Gastroesophageal reflux disease with esophagitis and heartburn.",
        },
        {
            "record_id": "diag-endoscopy",
            "patient_id": "pat-017",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2023-03-25T08:00:00Z",
            "text": "DiagnosticReport: Upper Endoscopy EGD | Conclusion: Grade A reflux esophagitis, negative for Barrett esophagus or ulceration.",
        },

        # Hematology group
        {
            "record_id": "obs-hemoglobin",
            "patient_id": "pat-018",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2024-06-25T09:30:00Z",
            "text": "Observation: Hemoglobin in Blood | Value: 9.8 g/dL | Microcytic anemia due to iron deficiency.",
        },
        {
            "record_id": "cond-anemia",
            "patient_id": "pat-018",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2024-06-25T10:00:00Z",
            "text": "Condition: Iron deficiency anemia with fatigue, pallor, and low ferritin.",
        },

        # Thyroid / Endocrinology group
        {
            "record_id": "obs-tsh",
            "patient_id": "pat-019",
            "resource_type": "Observation",
            "source": "fhir_document",
            "date": "2024-04-05T10:00:00Z",
            "text": "Observation: Thyrotropin TSH in Serum | Value: 7.2 uIU/mL | High elevated TSH primary hypothyroidism.",
        },
        {
            "record_id": "cond-hypothyroidism",
            "patient_id": "pat-019",
            "resource_type": "Condition",
            "source": "fhir_document",
            "date": "2024-04-06T11:00:00Z",
            "text": "Condition: Primary hypothyroidism on Levothyroxine replacement therapy.",
        },

        # Oncology / Screening group
        {
            "record_id": "diag-colonoscopy",
            "patient_id": "pat-020",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2023-09-14T08:30:00Z",
            "text": "DiagnosticReport: Screening Colonoscopy | Conclusion: Two benign tubular adenomas resected, repeat in 5 years.",
        },
        {
            "record_id": "diag-mammogram",
            "patient_id": "pat-021",
            "resource_type": "DiagnosticReport",
            "source": "fhir_document",
            "date": "2024-10-15T10:00:00Z",
            "text": "DiagnosticReport: Screening Digital Mammography | Conclusion: BI-RADS Category 1: Negative normal bilateral examination.",
        },
    ]

    # Fill remainder up to exactly 50 records with synthetic clinical observations & notes across dates
    for i in range(len(raw_records) + 1, 51):
        month = (i % 12) + 1
        day = (i % 25) + 1
        year = 2023 if i % 2 == 0 else 2024
        date_str = f"{year}-{month:02d}-{day:02d}T10:00:00Z"
        res_type = "Observation" if i % 3 == 0 else ("Condition" if i % 3 == 1 else "DiagnosticReport")
        src = "ai_summary" if i % 5 == 0 else "fhir_document"

        raw_records.append(
            {
                "record_id": f"rec-synthetic-{i:03d}",
                "patient_id": f"pat-syn-{i % 15:03d}",
                "resource_type": res_type,
                "source": src,
                "date": date_str,
                "text": f"{res_type}: Routine clinical monitoring examination #{i} showing stable health indicators and standard physical evaluation.",
            }
        )

    # Embed and upsert all 50 records in batches
    texts = [r["text"] for r in raw_records]
    embeddings = emb_gen.generate_embeddings(texts, batch_size=32)

    vector_records = []
    for idx, r in enumerate(raw_records):
        ts = parse_datetime_to_timestamp(r["date"])
        metadata = {
            "record_id": r["record_id"],
            "patient_id": r["patient_id"],
            "resource_type": r["resource_type"],
            "source": r["source"],
            "date": ts,
            "snippet": r["text"][:200],
            "chunk_index": 0,
        }
        vector_records.append(
            VectorRecord(
                id=f"{r['record_id']}:{r['source']}:0",
                embedding=embeddings[idx],
                document=r["text"],
                metadata=metadata,
            )
        )

    isolate_vector_store.upsert(vector_records, batch_size=64)
    return isolate_vector_store


@pytest.mark.asyncio
class TestSemanticSearchIntegration:
    """Integration test suite executing requests against POST /search with seeded data."""

    async def test_semantic_match_ranks_first(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Query 'high blood sugar' retrieves diabetes/hyperglycemia records at rank 1."""
        response = await async_client.post(
            "/search",
            json={"query": "high blood sugar"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "high blood sugar"
        assert data["count"] > 0
        assert len(data["results"]) <= 5

        top_match = data["results"][0]
        # Semantic match should find diabetes/glucose records despite exact keyword variations
        assert (
            "glucose" in top_match["snippet"].lower()
            or "hyperglycemia" in top_match["snippet"].lower()
            or "diabetes" in top_match["snippet"].lower()
            or "glycemic" in top_match["snippet"].lower()
        )
        # Relevance score in [0, 1]
        assert 0.0 <= top_match["score"] <= 1.0
        assert top_match["score"] > 0.4

    async def test_returns_at_most_5_results_sorted_descending(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Search returns at most 5 results, ordered strictly by score descending."""
        response = await async_client.post(
            "/search",
            json={"query": "routine health examination and blood test"},
        )
        assert response.status_code == 200
        data = response.json()

        results = data["results"]
        assert len(results) <= 5
        assert data["count"] == len(results)

        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    async def test_resource_type_filter(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Filter by resource_type returns only records matching that FHIR type."""
        response = await async_client.post(
            "/search?resource_type=Observation",
            json={"query": "elevated test reading"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0

        for item in data["results"]:
            assert item["resource_type"] == "Observation"

    async def test_date_range_filter(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Filter by date_from and date_to restricts results to that time window."""
        date_from = "2024-05-01T00:00:00Z"
        date_to = "2024-05-31T23:59:59Z"

        response = await async_client.post(
            f"/search?date_from={date_from}&date_to={date_to}",
            json={"query": "glucose blood test"},
        )
        assert response.status_code == 200
        data = response.json()

        ts_from = parse_datetime_to_timestamp(date_from)
        ts_to = parse_datetime_to_timestamp(date_to)

        for item in data["results"]:
            item_ts = parse_datetime_to_timestamp(item["date"])
            assert ts_from <= item_ts <= ts_to

    async def test_combined_resource_type_and_date_range_filter(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Combined resource_type and date range pre-filtering works in harmony."""
        response = await async_client.post(
            "/search?resource_type=Observation&date_from=2024-01-01T00:00:00Z&date_to=2024-12-31T23:59:59Z",
            json={"query": "abnormal clinical finding"},
        )
        assert response.status_code == 200
        data = response.json()

        for item in data["results"]:
            assert item["resource_type"] == "Observation"
            item_ts = parse_datetime_to_timestamp(item["date"])
            assert parse_datetime_to_timestamp("2024-01-01T00:00:00Z") <= item_ts <= parse_datetime_to_timestamp("2024-12-31T23:59:59Z")

    async def test_validation_errors(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Invalid date range (date_from > date_to) and empty queries yield 422 Unprocessable Entity."""
        # 1. date_from > date_to
        resp_date = await async_client.post(
            "/search?date_from=2024-12-31T00:00:00Z&date_to=2024-01-01T00:00:00Z",
            json={"query": "hypertension"},
        )
        assert resp_date.status_code == 422

        # 2. Empty query string
        resp_empty = await async_client.post(
            "/search",
            json={"query": ""},
        )
        assert resp_empty.status_code == 422

        # 3. Whitespace query string
        resp_whitespace = await async_client.post(
            "/search",
            json={"query": "    "},
        )
        assert resp_whitespace.status_code == 422

    async def test_empty_results_when_nothing_matches(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Return an empty results list (not an error) when no records match filter criteria."""
        response = await async_client.post(
            "/search?resource_type=NonExistentResource",
            json={"query": "hypertension"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["results"] == []

    async def test_latency_under_2_seconds(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Search execution must return well under 2 seconds for a 50-record dataset."""
        start = time.perf_counter()
        response = await async_client.post(
            "/search",
            json={"query": "patient with respiratory shortness of breath and cough"},
        )
        total_time = time.perf_counter() - start

        assert response.status_code == 200
        assert total_time < 2.0
        # Check that took_ms reported in payload is also reasonable
        assert response.json()["took_ms"] < 2000.0

    async def test_api_v1_and_root_search_parity(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Both POST /search and POST /api/v1/search endpoints return identical valid responses."""
        resp_root = await async_client.post(
            "/search",
            json={"query": "kidney disease creatinine"},
        )
        resp_v1 = await async_client.post(
            "/api/v1/search",
            json={"query": "kidney disease creatinine"},
        )
        assert resp_root.status_code == 200
        assert resp_v1.status_code == 200
        assert resp_root.json()["count"] == resp_v1.json()["count"]
        assert len(resp_root.json()["results"]) == len(resp_v1.json()["results"])

    async def test_patient_id_filter_restricts_to_patient(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Filter by patient_id via query param or body restricts results exclusively to that patient."""
        # 1. Via Query Param
        resp_param = await async_client.post(
            "/search?patient_id=pat-001",
            json={"query": "diabetes and high blood sugar"},
        )
        assert resp_param.status_code == 200
        data_param = resp_param.json()
        assert data_param["count"] > 0
        for item in data_param["results"]:
            assert item["patient_id"] == "pat-001"

        # 2. Via Request Body
        resp_body = await async_client.post(
            "/search",
            json={"query": "hypertension blood pressure", "patient_id": "pat-005"},
        )
        assert resp_body.status_code == 200
        data_body = resp_body.json()
        assert data_body["count"] > 0
        for item in data_body["results"]:
            assert item["patient_id"] == "pat-005"

    async def test_date_to_date_only_includes_end_of_day_records(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Date-only date_to='YYYY-MM-DD' properly includes records timestamped later on that calendar day (23:59:59 UTC)."""
        # obs-glucose-high has date 2024-05-01T10:00:00Z.
        # Querying with date_to=2024-05-01 must include this record.
        response = await async_client.post(
            "/search?date_from=2024-05-01&date_to=2024-05-01",
            json={"query": "glucose blood sugar"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] > 0
        found_records = [item["record_id"] for item in data["results"]]
        assert "obs-glucose-high" in found_records

    async def test_top_k_parameter_limits_result_count(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Custom top_k parameter (via query or body) limits the number of returned results."""
        # Top_k = 2 via query param
        resp_param = await async_client.post(
            "/search?top_k=2",
            json={"query": "routine health examination"},
        )
        assert resp_param.status_code == 200
        data_param = resp_param.json()
        assert len(data_param["results"]) == 2
        assert data_param["count"] == 2

        # Top_k = 3 via request body
        resp_body = await async_client.post(
            "/search",
            json={"query": "routine health examination", "top_k": 3},
        )
        assert resp_body.status_code == 200
        data_body = resp_body.json()
        assert len(data_body["results"]) == 3
        assert data_body["count"] == 3

    async def test_orphan_chunk_cleanup_on_record_update(
        self, async_client: AsyncClient, seeded_vector_store: VectorStore
    ):
        """Re-indexing a record with fewer chunks purges orphan chunk vectors from the vector store."""
        emb_gen = get_embedding_generator()
        # Seed record-multi with 3 chunks
        chunks = [
            "Clinical multi-chunk report part 1: initial diagnosis and findings.",
            "Clinical multi-chunk report part 2: detailed laboratory results and panel analysis.",
            "Clinical multi-chunk report part 3: discharge medication and follow up instructions.",
        ]
        embeddings = emb_gen.generate_embeddings(chunks)
        records = [
            VectorRecord(
                id=f"rec-multi:fhir_document:{idx}",
                embedding=embeddings[idx],
                document=chunks[idx],
                metadata={
                    "record_id": "rec-multi",
                    "patient_id": "pat-multi",
                    "resource_type": "DiagnosticReport",
                    "source": "fhir_document",
                    "date": 1714560000,
                    "snippet": chunks[idx][:100],
                    "chunk_index": idx,
                },
            )
            for idx in range(3)
        ]
        seeded_vector_store.upsert(records)

        # Verify all 3 chunks exist
        existing = seeded_vector_store.collection.get(where={"record_id": "rec-multi"})
        assert len(existing["ids"]) == 3

        # Now simulate reindexing: delete old chunks for rec-multi and upsert 1 chunk
        seeded_vector_store.delete_by_record_id("rec-multi")
        new_chunk = ["Updated report with single consolidated summary."]
        new_emb = emb_gen.generate_embeddings(new_chunk)
        new_record = [
            VectorRecord(
                id="rec-multi:fhir_document:0",
                embedding=new_emb[0],
                document=new_chunk[0],
                metadata={
                    "record_id": "rec-multi",
                    "patient_id": "pat-multi",
                    "resource_type": "DiagnosticReport",
                    "source": "fhir_document",
                    "date": 1714560000,
                    "snippet": new_chunk[0][:100],
                    "chunk_index": 0,
                },
            )
        ]
        seeded_vector_store.upsert(new_record)

        # Verify only 1 chunk remains and chunks 1 and 2 are gone
        remaining = seeded_vector_store.collection.get(where={"record_id": "rec-multi"})
        assert len(remaining["ids"]) == 1
        assert remaining["ids"][0] == "rec-multi:fhir_document:0"

