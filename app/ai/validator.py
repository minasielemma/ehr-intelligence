"""Clinical evidence validation and hallucination detection engine.

Verifies that all diagnoses, lab findings, and assertions in generated summaries
are strictly grounded in underlying FHIR source records. Flags or rejects unsupported claims.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.ai.extractor import ExtractedClinicalRecord
from app.core.logging import get_logger
from app.schemas.summary import ClinicalSummaryResponse, ConfidenceLevel, ConfidenceScore

logger = get_logger(__name__)


CLINICAL_ACRONYM_MAP = {
    "cad": "coronary artery disease",
    "ckd": "chronic kidney disease",
    "chf": "congestive heart failure",
    "copd": "chronic obstructive pulmonary disease",
    "dvt": "deep vein thrombosis",
    "pe": "pulmonary embolism",
    "hiv": "human immunodeficiency virus",
    "uti": "urinary tract infection",
    "htn": "hypertension",
    "t2dm": "type 2 diabetes mellitus",
    "t1dm": "type 1 diabetes mellitus",
    "gerd": "gastroesophageal reflux disease",
    "mi": "myocardial infarction",
    "afib": "atrial fibrillation",
    "af": "atrial fibrillation",
    "cva": "cerebrovascular accident",
    "tia": "transient ischemic attack",
    "esrd": "end stage renal disease",
    "osa": "obstructive sleep apnea",
    "pud": "peptic ulcer disease",
    "ra": "rheumatoid arthritis",
    "sle": "systemic lupus erythematosus",
    "ibd": "inflammatory bowel disease",
    "ibs": "irritable bowel syndrome",
    "tb": "tuberculosis",
    "flu": "influenza",
    "uri": "upper respiratory infection",
}

CLINICAL_QUALIFIER_STOPWORDS = {
    "type", "stage", "grade", "class", "status", "post", "history", "hx",
    "and", "with", "due", "without", "acute", "chronic", "recurrent",
    "mild", "moderate", "severe", "unspecified", "primary", "secondary",
    "bilateral", "left", "right", "confirmed", "suspected", "active", "resolved",
}


@dataclass
class EvidenceValidationResult:
    """Result of cross-referencing generated summary against source evidence."""
    is_valid: bool
    unsupported_claims: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    adjusted_confidence: Optional[ConfidenceScore] = None
    should_reject: bool = False


class EvidenceValidator:
    """Verifies that generated summaries adhere strictly to source clinical records."""

    @classmethod
    def validate_summary(
        cls,
        summary: ClinicalSummaryResponse,
        source: ExtractedClinicalRecord,
    ) -> EvidenceValidationResult:
        """Cross-examine a generated ClinicalSummaryResponse against its ExtractedClinicalRecord source."""
        unsupported: List[str] = []
        warnings: List[str] = []

        # 1. Verify Patient ID consistency
        if summary.patient_id != source.patient.id:
            unsupported.append(
                f"Patient ID mismatch: summary references '{summary.patient_id}', expected '{source.patient.id}'"
            )

        # 2. Build canonical terms index from source record for fuzzy matching
        source_texts: List[str] = []
        for cond in source.conditions:
            cond_lower = cond.name.lower()
            source_texts.append(cond_lower)
            # Index known acronym aliases
            for acr, full in CLINICAL_ACRONYM_MAP.items():
                if full in cond_lower:
                    source_texts.append(acr)
        for obs in source.observations:
            source_texts.append(obs.name.lower())
            if obs.value:
                source_texts.append(str(obs.value).lower())
        for dr in source.diagnostic_reports:
            source_texts.append(dr.name.lower())
            if dr.conclusion:
                source_texts.append(dr.conclusion.lower())
        for note in source.clinical_notes:
            source_texts.append(note.content_text.lower())
        for med in source.medications:
            source_texts.append(med.name.lower())

        combined_source_corpus = " ".join(source_texts)

        def is_term_grounded(term: str) -> bool:
            """Check if a clinical term or its acronym alias is present in the source corpus."""
            if re.search(rf"\b{re.escape(term)}\b", combined_source_corpus):
                return True
            full_expansion = CLINICAL_ACRONYM_MAP.get(term)
            if full_expansion and full_expansion in combined_source_corpus:
                return True
            return False

        # 3. Verify Key Diagnoses
        for diag in summary.key_diagnoses:
            diag_lower = diag.lower().strip()
            # Clean common qualifier prefixes
            clean_diag = re.sub(r"^(active|history of|suspected|confirmed|chronic|acute)\s+", "", diag_lower)
            # Tokenize into words >= 2 chars to support clinical acronyms
            tokens = [t for t in re.findall(r"\b[a-z0-9]{2,}\b", clean_diag)]
            if not tokens:
                unsupported.append(f"Unsupported Diagnosis: '{diag}' contains no verifiable medical terminology")
                continue

            # Short diagnosis or recognized clinical acronym: exact grounded check
            if len(tokens) == 1 and (tokens[0] in CLINICAL_ACRONYM_MAP or len(tokens[0]) <= 3):
                if not is_term_grounded(tokens[0]):
                    unsupported.append(f"Unsupported Diagnosis: '{diag}' was not found in source clinical records")
                continue

            # Multi-word diagnosis: filter out common non-discriminating qualifiers
            substantive_tokens = [t for t in tokens if t not in CLINICAL_QUALIFIER_STOPWORDS and not t.isdigit()]
            if not substantive_tokens:
                substantive_tokens = tokens

            # Require multi-token threshold: at least 60% of substantive tokens must be grounded in source
            matched_count = sum(1 for t in substantive_tokens if is_term_grounded(t))
            match_ratio = matched_count / len(substantive_tokens)

            if match_ratio < 0.60:
                unsupported.append(f"Unsupported Diagnosis: '{diag}' was not found in source clinical records")


        # 4. Verify Laboratory Claims
        for lab_claim in summary.recent_diagnostic_records.laboratory:
            tokens = [t for t in re.findall(r"\b[a-z0-9]{2,}\b", lab_claim.lower())]
            # Ignore common lab words
            filtered_tokens = [
                t for t in tokens
                if t not in ["normal", "abnormal", "level", "value", "panel", "test", "result", "serum", "blood", "elevated", "low", "high"]
            ]
            if filtered_tokens and not any(re.search(rf"\b{re.escape(t)}\b", combined_source_corpus) for t in filtered_tokens):
                warnings.append(f"Unverified Lab Claim: '{lab_claim}' lacks corresponding observation in source data")

        # 5. Check Source References
        source_ref_set = set(source.source_references)
        for ref in summary.source_references:
            if ref not in source_ref_set:
                warnings.append(f"Dangling Source Reference: '{ref}' does not exist in extracted FHIR resources")

        # 6. Evaluate Rejection Criteria and Adjust Confidence
        should_reject = False
        adjusted_conf = summary.confidence

        if len(unsupported) > 0:
            logger.warning(
                "Detected %d unsupported claims in summary for patient [%s]: %s",
                len(unsupported),
                source.patient.id,
                unsupported,
            )
            # Downgrade confidence if model hallucinated diagnoses
            adjusted_conf = ConfidenceScore(
                level=ConfidenceLevel.LOW,
                explanation=f"Reduced to low confidence due to {len(unsupported)} unsupported clinical claims: {'; '.join(unsupported[:2])}",
            )
            # Reject if critical/unsupported claims or patient ID mismatch
            if len(unsupported) >= 1 or summary.patient_id != source.patient.id:
                should_reject = True
        elif len(warnings) > 0:
            adjusted_conf = ConfidenceScore(
                level=ConfidenceLevel.MODERATE if len(warnings) <= 2 else ConfidenceLevel.LOW,
                explanation=f"Moderate confidence: unverified diagnostic claims or dangling references detected: {'; '.join(warnings[:2])}",
            )

        is_valid = len(unsupported) == 0 and len(warnings) == 0

        return EvidenceValidationResult(
            is_valid=is_valid,
            unsupported_claims=unsupported,
            warnings=warnings,
            adjusted_confidence=adjusted_conf,
            should_reject=should_reject,
        )

