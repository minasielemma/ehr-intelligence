"""Unit test suite for clinical text extraction, chunking, score conversion, and Chroma filters."""

import pytest
from pydantic import ValidationError

from app.schemas.search import SearchRequest
from app.search.extraction import (
    build_chroma_filters,
    chunk_text,
    distance_to_score,
    extract_resource_date,
    extract_searchable_text_from_fhir_resource,
    format_timestamp_to_iso,
    parse_datetime_to_timestamp,
    strip_html_tags,
)


class TestHTMLStripping:
    """Tests for narrative HTML/XML cleaning and entity resolution."""

    def test_strip_html_basic_and_nested(self):
        html_input = '<div xmlns="http://www.w3.org/1999/xhtml"><p>Patient presents with <b>hypertension</b>.</p></div>'
        assert strip_html_tags(html_input) == "Patient presents with hypertension."

    def test_strip_html_entities(self):
        html_input = "<p>Glucose &gt; 140 mg/dL &amp; HbA1c &gt; 7.5%</p>"
        assert strip_html_tags(html_input) == "Glucose > 140 mg/dL & HbA1c > 7.5%"

    def test_strip_html_empty_or_none(self):
        assert strip_html_tags("") == ""
        assert strip_html_tags(None) == ""


class TestFHIRTextExtraction:
    """Tests for extracting sensible clinical text from FHIR R4 resources."""

    def test_extract_observation_with_value_quantity(self):
        resource = {
            "resourceType": "Observation",
            "id": "obs-glucose-1",
            "text": {"div": "<div>Blood Glucose Test</div>"},
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "2339-0",
                        "display": "Glucose [Mass/volume] in Blood",
                    }
                ],
                "text": "Random Blood Glucose",
            },
            "valueQuantity": {"value": 195, "unit": "mg/dL"},
            "interpretation": [
                {
                    "coding": [
                        {"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "H", "display": "High"}
                    ]
                }
            ],
            "note": [{"text": "Patient fasting status unknown."}],
        }
        text = extract_searchable_text_from_fhir_resource(resource)
        assert "Blood Glucose Test" in text
        assert "Random Blood Glucose" in text
        assert "Value: 195 mg/dL" in text
        assert "Interpretation: High" in text
        assert "Note: Patient fasting status unknown." in text
        assert text.startswith("Observation:")

    def test_extract_condition_with_codes(self):
        resource = {
            "resourceType": "Condition",
            "id": "cond-dm2",
            "clinicalStatus": {"coding": [{"code": "active", "display": "Active"}]},
            "code": {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "44054006",
                        "display": "Type 2 diabetes mellitus",
                    }
                ],
                "text": "Type 2 Diabetes Mellitus with hyperglycemia",
            },
            "note": [{"text": "Managed with Metformin 500mg BID."}],
        }
        text = extract_searchable_text_from_fhir_resource(resource)
        assert "Type 2 Diabetes Mellitus" in text
        assert "Active" in text
        assert "Managed with Metformin" in text

    def test_extract_diagnostic_report_conclusion(self):
        resource = {
            "resourceType": "DiagnosticReport",
            "id": "diag-ecg-1",
            "code": {"text": "12-Lead Electrocardiogram"},
            "conclusion": "Sinus rhythm with occasional premature ventricular contractions.",
        }
        text = extract_searchable_text_from_fhir_resource(resource)
        assert "12-Lead Electrocardiogram" in text
        assert "Conclusion: Sinus rhythm with occasional" in text

    def test_extract_fallback_json_flattening(self):
        # Resource without standard code/text fields
        resource = {
            "resourceType": "Device",
            "id": "dev-01",
            "modelNumber": "Pacemaker-XYZ",
            "manufacturer": "MedTech Corp",
        }
        text = extract_searchable_text_from_fhir_resource(resource)
        assert "Pacemaker-XYZ" in text
        assert "MedTech Corp" in text


class TestTextChunking:
    """Tests for sliding window token/word chunking."""

    def test_short_text_single_chunk(self):
        text = "Patient vitals are stable. Temperature is 98.6 F."
        chunks = chunk_text(text, chunk_size=50, chunk_overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_chunking_with_overlap(self):
        # 100 distinct words
        words = [f"word_{i}" for i in range(100)]
        long_text = " ".join(words)

        chunks = chunk_text(long_text, chunk_size=40, chunk_overlap=10)
        assert len(chunks) > 1

        # Check overlap between first and second chunk
        chunk_0_words = chunks[0].split()
        chunk_1_words = chunks[1].split()
        assert len(chunk_0_words) == 40
        # The last 10 words of chunk 0 must match the first 10 words of chunk 1
        assert chunk_0_words[-10:] == chunk_1_words[:10]

    def test_empty_text_chunking(self):
        assert chunk_text("") == []
        assert chunk_text("    ") == []


class TestDateParsingAndExtraction:
    """Tests for ISO 8601 parsing, timestamp conversion, and FHIR resource date discovery."""

    def test_parse_datetime_iso_zulu(self):
        ts = parse_datetime_to_timestamp("2024-05-01T10:00:00Z")
        assert ts is not None
        assert ts == 1714557600
        assert format_timestamp_to_iso(ts) == "2024-05-01T10:00:00Z"

    def test_parse_date_only_string(self):
        ts = parse_datetime_to_timestamp("2024-05-01")
        assert ts is not None
        assert format_timestamp_to_iso(ts).startswith("2024-05-01")

    def test_parse_date_only_end_of_day(self):
        ts_start = parse_datetime_to_timestamp("2024-12-31", is_end_of_day=False)
        ts_end = parse_datetime_to_timestamp("2024-12-31", is_end_of_day=True)
        assert ts_start is not None and ts_end is not None
        assert ts_end > ts_start
        assert ts_end - ts_start == 86399
        assert format_timestamp_to_iso(ts_end) == "2024-12-31T23:59:59Z"

    def test_extract_resource_date_precedence(self):
        res = {
            "resourceType": "Observation",
            "effectiveDateTime": "2024-06-15T12:00:00Z",
            "meta": {"lastUpdated": "2024-01-01T00:00:00Z"},
        }
        ts = extract_resource_date(res)
        assert ts == 1718452800


class TestScoreConversion:
    """Tests for converting Chroma cosine distance to [0, 1] relevance score."""

    def test_score_exact_match(self):
        assert distance_to_score(0.0) == 1.0

    def test_score_user_example(self):
        # Example from specification: cosine distance 0.17 -> score 0.83
        assert distance_to_score(0.17) == 0.83

    def test_score_bounding_and_clamping(self):
        assert distance_to_score(-0.0001) == 1.0
        assert distance_to_score(1.0) == 0.0
        assert distance_to_score(1.5) == 0.0


class TestFilterConstruction:
    """Tests for ChromaDB pre-filtering dictionary construction."""

    def test_no_filters(self):
        assert build_chroma_filters() is None

    def test_resource_type_only(self):
        filters = build_chroma_filters(resource_type="Observation")
        assert filters == {"resource_type": "Observation"}

    def test_patient_id_only(self):
        filters = build_chroma_filters(patient_id="pat-12345")
        assert filters == {"patient_id": "pat-12345"}

    def test_date_range_only(self):
        filters = build_chroma_filters(date_from_ts=1700000000, date_to_ts=1700050000)
        assert filters == {
            "$and": [
                {"date": {"$gte": 1700000000}},
                {"date": {"$lte": 1700050000}},
            ]
        }

    def test_combined_resource_and_date_range(self):
        filters = build_chroma_filters(
            resource_type="Condition",
            date_from_ts=1700000000,
            date_to_ts=1700050000,
        )
        assert filters == {
            "$and": [
                {"resource_type": "Condition"},
                {"date": {"$gte": 1700000000}},
                {"date": {"$lte": 1700050000}},
            ]
        }

    def test_combined_all_filters(self):
        filters = build_chroma_filters(
            resource_type="Observation",
            patient_id="pat-999",
            date_from_ts=1700000000,
            date_to_ts=1700050000,
        )
        assert filters == {
            "$and": [
                {"resource_type": "Observation"},
                {"patient_id": "pat-999"},
                {"date": {"$gte": 1700000000}},
                {"date": {"$lte": 1700050000}},
            ]
        }


class TestSearchRequestValidation:
    """Tests for SearchRequest Pydantic validation."""

    def test_valid_query(self):
        req = SearchRequest(query="elevated glucose")
        assert req.query == "elevated glucose"

    def test_whitespace_query_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="    ")

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="")


class TestIndexingService:
    """Tests for IndexingService methods and signatures."""

    @pytest.mark.asyncio
    async def test_indexing_service_has_async_index_fhir_bundle(self):
        from unittest.mock import MagicMock
        from app.search.indexing import IndexingService

        mock_vs = MagicMock()
        mock_emb = MagicMock()
        mock_emb.generate_embeddings.return_value = [[0.1] * 384]

        service = IndexingService(vector_store=mock_vs, embedding_generator=mock_emb)
        assert hasattr(service, "index_fhir_bundle")
        assert hasattr(service, "index_fhir_bundle_sync")

        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "obs-unit-test",
                        "code": {"text": "Blood Pressure"},
                        "valueString": "120/80 mmHg",
                    }
                }
            ],
        }
        res = await service.index_fhir_bundle(
            bundle_json=bundle,
            patient_id="pat-unit-1",
            bundle_id="b-unit-1",
        )
        assert res == 1
        assert mock_vs.upsert.called
        assert mock_vs.delete_by_record_ids.called

