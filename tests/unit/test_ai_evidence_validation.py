"""Unit tests for Evidence Grounding Validator and Hallucination Detection."""

import pytest

from app.ai.extractor import (
    ExtractedClinicalRecord,
    ExtractedCondition,
    ExtractedObservation,
    ExtractedPatient,
)
from app.ai.validator import EvidenceValidator
from app.schemas.summary import (
    ClinicalSummaryResponse,
    ConfidenceLevel,
    ConfidenceScore,
    DiagnosticRecordsSummary,
    ModelMetadata,
)


@pytest.fixture
def sample_source_record():
    """Build a known source clinical record for evidence comparison."""
    patient = ExtractedPatient(id="pat-evid-1", mrn="MRN-1", source_reference="Patient/pat-evid-1")
    conditions = [
        ExtractedCondition(
            id="c1",
            name="Chronic Kidney Disease Stage 3",
            clinical_status="active",
            verification_status="confirmed",
            source_reference="Condition/c1",
        ),
        ExtractedCondition(
            id="c2",
            name="Type 2 Diabetes Mellitus",
            clinical_status="active",
            verification_status="confirmed",
            source_reference="Condition/c2",
        ),
    ]
    observations = [
        ExtractedObservation(
            id="o1",
            name="Serum Creatinine",
            category="laboratory",
            value="1.8 mg/dL",
            numeric_value=1.8,
            reference_range_text="0.7 - 1.3 mg/dL",
            interpretation="H",
            is_abnormal=True,
            source_reference="Observation/o1",
        )
    ]
    return ExtractedClinicalRecord(
        patient=patient,
        conditions=conditions,
        observations=observations,
        source_references=["Patient/pat-evid-1", "Condition/c1", "Condition/c2", "Observation/o1"],
        chief_concern="Renal function evaluation",
    )


def test_valid_grounded_summary_passes(sample_source_record):
    """Verify that a summary with grounded diagnoses passes validation with intact confidence."""
    summary = ClinicalSummaryResponse(
        patient_id="pat-evid-1",
        chief_concern="Renal function evaluation",
        key_diagnoses=["Chronic Kidney Disease Stage 3", "Type 2 Diabetes Mellitus"],
        recent_diagnostic_records=DiagnosticRecordsSummary(
            laboratory=["Serum Creatinine 1.8 mg/dL (Elevated)"]
        ),
        flagged_anomalies=["Abnormal Serum Creatinine: 1.8 mg/dL"],
        clinical_summary="Patient with chronic kidney disease stage 3 and diabetes mellitus demonstrates elevated creatinine.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="Well grounded"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=["Patient/pat-evid-1", "Condition/c1", "Observation/o1"],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )

    result = EvidenceValidator.validate_summary(summary, sample_source_record)
    assert result.is_valid is True
    assert len(result.unsupported_claims) == 0
    assert result.should_reject is False
    assert result.adjusted_confidence.level == ConfidenceLevel.HIGH


def test_hallucinated_diagnosis_detected_and_downgrades_confidence(sample_source_record):
    """Verify that fabricating an unsupported diagnosis is detected and downgrades confidence."""
    summary = ClinicalSummaryResponse(
        patient_id="pat-evid-1",
        chief_concern="Renal function evaluation",
        key_diagnoses=["Chronic Kidney Disease Stage 3", "Malignant Melanoma"],  # Melanoma is fabricated!
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient has chronic kidney disease stage 3 and malignant melanoma.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="Allegedly high"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=["Patient/pat-evid-1", "Condition/c1"],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )

    result = EvidenceValidator.validate_summary(summary, sample_source_record)
    assert result.is_valid is False
    assert len(result.unsupported_claims) >= 1
    assert any("Melanoma" in claim for claim in result.unsupported_claims)
    assert result.adjusted_confidence.level == ConfidenceLevel.LOW
    assert "unsupported clinical claims" in result.adjusted_confidence.explanation


def test_multiple_hallucinations_triggers_rejection(sample_source_record):
    """Verify that multiple unsupported diagnoses triggers rejection flag."""
    summary = ClinicalSummaryResponse(
        patient_id="pat-evid-1",
        key_diagnoses=["Acute Myocardial Infarction", "Multiple Sclerosis"],
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient suffered an acute myocardial infarction complicated by multiple sclerosis.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="High"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=[],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )

    result = EvidenceValidator.validate_summary(summary, sample_source_record)
    assert result.is_valid is False
    assert result.should_reject is True
    assert len(result.unsupported_claims) >= 2


def test_patient_id_mismatch_triggers_rejection(sample_source_record):
    """Verify that summary generated for wrong patient is rejected immediately."""
    summary = ClinicalSummaryResponse(
        patient_id="pat-WRONG-999",
        key_diagnoses=["Type 2 Diabetes Mellitus"],
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient with diabetes.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="High"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=[],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )

    result = EvidenceValidator.validate_summary(summary, sample_source_record)
    assert result.is_valid is False
    assert result.should_reject is True
    assert any("Patient ID mismatch" in claim for claim in result.unsupported_claims)


def test_short_clinical_acronym_grounding(sample_source_record):
    """Verify that clinical acronyms (e.g. CKD, CAD, HIV) are correctly validated."""
    # CKD is in source ("Chronic Kidney Disease Stage 3")
    summary_valid = ClinicalSummaryResponse(
        patient_id="pat-evid-1",
        key_diagnoses=["CKD Stage 3", "Type 2 Diabetes Mellitus"],
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient with CKD stage 3 and diabetes mellitus.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="Valid"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=["Patient/pat-evid-1", "Condition/c1"],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )
    result_valid = EvidenceValidator.validate_summary(summary_valid, sample_source_record)
    assert result_valid.is_valid is True
    assert len(result_valid.unsupported_claims) == 0

    # HIV is NOT in source - must be detected as unsupported!
    summary_invalid = ClinicalSummaryResponse(
        patient_id="pat-evid-1",
        key_diagnoses=["CKD Stage 3", "HIV"],
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient with CKD and HIV.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="High"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=["Patient/pat-evid-1"],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )
    result_invalid = EvidenceValidator.validate_summary(summary_invalid, sample_source_record)
    assert result_invalid.is_valid is False
    assert any("HIV" in claim for claim in result_invalid.unsupported_claims)


def test_multi_token_hallucination_with_common_qualifier_rejected(sample_source_record):
    """Verify that a hallucinated diagnosis sharing only common words (like 'chronic') is rejected."""
    # Source has 'Chronic Kidney Disease Stage 3', but NOT 'Chronic Glioblastoma Multiforme'
    summary = ClinicalSummaryResponse(
        patient_id="pat-evid-1",
        key_diagnoses=["Chronic Glioblastoma Multiforme"],
        recent_diagnostic_records=DiagnosticRecordsSummary(),
        flagged_anomalies=[],
        clinical_summary="Patient with chronic glioblastoma multiforme.",
        confidence=ConfidenceScore(level=ConfidenceLevel.HIGH, explanation="High"),
        disclaimer="AI-generated summary. Not a clinical diagnosis or medical decision.",
        source_references=["Patient/pat-evid-1"],
        model_metadata=ModelMetadata(provider="ollama", model="gemma3:12b"),
    )
    result = EvidenceValidator.validate_summary(summary, sample_source_record)
    assert result.is_valid is False
    assert any("Glioblastoma" in claim for claim in result.unsupported_claims)

