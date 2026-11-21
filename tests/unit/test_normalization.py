"""Unit tests for date, gender, MRN, clinical text, and demographic normalizers."""

import pytest
from app.ingestion.cleaners.text_cleaner import ClinicalTextCleaner
from app.ingestion.normalizers.date_normalizer import DateNormalizer
from app.ingestion.normalizers.demographics import DemographicNormalizer
from app.ingestion.normalizers.gender_normalizer import GenderNormalizer
from app.ingestion.normalizers.mrn_normalizer import MRNNormalizer
from app.schemas.canonical import MappingProfile


# ==============================================================================
# Date Normalizer Tests
# ==============================================================================

def test_date_normalizer_iso() -> None:
    """Verify standard ISO 8601 date normalizes properly."""
    res = DateNormalizer.normalize_date("1990-11-25")
    assert res.is_valid is True
    assert res.normalized_value == "1990-11-25"
    assert res.is_ambiguous is False


def test_date_normalizer_unambiguous_day_first() -> None:
    """Verify DD/MM/YYYY is parsed unambiguously when day > 12."""
    res = DateNormalizer.normalize_date("28/02/1985")
    assert res.is_valid is True
    assert res.normalized_value == "1985-02-28"
    assert res.is_ambiguous is False


def test_date_normalizer_unambiguous_month_first() -> None:
    """Verify MM/DD/YYYY is parsed unambiguously when month portion has day > 12."""
    res = DateNormalizer.normalize_date("03/24/1995")
    assert res.is_valid is True
    assert res.normalized_value == "1995-03-24"
    assert res.is_ambiguous is False


def test_date_normalizer_symmetric() -> None:
    """Verify symmetric dates (day == month) parse cleanly without ambiguity."""
    res = DateNormalizer.normalize_date("06/06/2001")
    assert res.is_valid is True
    assert res.normalized_value == "2001-06-06"
    assert res.is_ambiguous is False


def test_date_normalizer_ambiguous_detection() -> None:
    """Verify date strings where day <= 12 and month <= 12 are strictly flagged as ambiguous."""
    res = DateNormalizer.normalize_date("04/05/2012")
    assert res.is_valid is False
    assert res.is_ambiguous is True
    assert res.normalized_value is None
    assert "Ambiguous date" in res.error_message


def test_date_normalizer_ambiguous_with_format_hint() -> None:
    """Verify ambiguous dates are resolved when a valid format hint is supplied."""
    res_us = DateNormalizer.normalize_date("04/05/2012", format_hint="MM/DD/YYYY")
    assert res_us.is_valid is True
    assert res_us.normalized_value == "2012-04-05"

    res_uk = DateNormalizer.normalize_date("04/05/2012", format_hint="DD/MM/YYYY")
    assert res_uk.is_valid is True
    assert res_uk.normalized_value == "2012-05-04"


def test_date_normalizer_invalid() -> None:
    """Verify non-existent calendar dates are rejected."""
    res = DateNormalizer.normalize_date("2021-02-31")
    assert res.is_valid is False
    assert "Invalid calendar date" in res.error_message


def test_date_normalizer_textual_month_formats() -> None:
    """Verify common clinical textual month dates normalize cleanly."""
    # Day-Month-Year
    res1 = DateNormalizer.normalize_date("14-Aug-1979")
    assert res1.is_valid is True
    assert res1.normalized_value == "1979-08-14"

    res2 = DateNormalizer.normalize_date("15/Nov/1990")
    assert res2.is_valid is True
    assert res2.normalized_value == "1990-11-15"

    res3 = DateNormalizer.normalize_date("04 July 2010")
    assert res3.is_valid is True
    assert res3.normalized_value == "2010-07-04"

    # Month-Day-Year
    res4 = DateNormalizer.normalize_date("Oct 12, 2023")
    assert res4.is_valid is True
    assert res4.normalized_value == "2023-10-12"

    res5 = DateNormalizer.normalize_date("March 4, 1982")
    assert res5.is_valid is True
    assert res5.normalized_value == "1982-03-04"

    # Year-Month-Day
    res6 = DateNormalizer.normalize_date("1979-Aug-14")
    assert res6.is_valid is True
    assert res6.normalized_value == "1979-08-14"

    # Invalid textual dates
    res_bad_month = DateNormalizer.normalize_date("14-Xyz-1979")
    assert res_bad_month.is_valid is False
    assert "Unrecognized month name" in res_bad_month.error_message

    res_bad_day = DateNormalizer.normalize_date("31-Apr-2021")
    assert res_bad_day.is_valid is False
    assert "Invalid calendar date" in res_bad_day.error_message



def test_date_normalizer_timestamp_with_timezone() -> None:
    """Verify timestamps with timezone offsets are converted to canonical UTC ISO string."""
    res = DateNormalizer.normalize_timestamp("2023-08-14T15:30:00+02:00")
    assert res.is_valid is True
    assert res.normalized_value == "2023-08-14T13:30:00Z"


# ==============================================================================
# Gender Normalizer Tests
# ==============================================================================

def test_gender_normalizer_mappings() -> None:
    """Verify canonical administrative gender code mappings."""
    for male_in in ["M", "Male", "male", "1", "BOY"]:
        norm, orig, tx = GenderNormalizer.normalize_gender(male_in)
        assert norm == "male"
        assert orig == male_in

    for fem_in in ["F", "Female", "female", "2"]:
        norm, orig, tx = GenderNormalizer.normalize_gender(fem_in)
        assert norm == "female"

    for other_in in ["O", "Other", "Non-binary", "X"]:
        norm, orig, tx = GenderNormalizer.normalize_gender(other_in)
        assert norm == "other"

    for unk_in in ["U", "Unknown", "Unspecified", "", None]:
        norm, orig, tx = GenderNormalizer.normalize_gender(unk_in)
        assert norm == "unknown"


# ==============================================================================
# MRN Normalizer Tests
# ==============================================================================

def test_mrn_normalizer_preserves_leading_zeros() -> None:
    """Verify MRN normalization trims whitespace while strictly preserving leading zeroes."""
    norm, orig, tx = MRNNormalizer.normalize_mrn("   000847291  \n")
    assert norm == "000847291"
    assert orig == "   000847291  \n"
    assert tx == "MRN_WHITESPACE_TRIMMED"


def test_mrn_normalizer_prefix_stripping() -> None:
    """Verify configurable MRN prefix removal."""
    norm, orig, tx = MRNNormalizer.normalize_mrn("HOSP-94827", strip_prefix="HOSP")
    assert norm == "94827"
    assert tx == "MRN_PREFIX_STRIPPED"


# ==============================================================================
# Clinical Text Cleaner Tests
# ==============================================================================

def test_clinical_text_cleaner_preserves_semantics() -> None:
    """Verify cleaner normalizes control chars and line endings without altering medical content."""
    messy_text = (
        "CHIEF COMPLAINT:\r\n"
        "Patient presents with chest tightness.\x00\x07\n\n\n"
        "VITAL SIGNS:\n"
        "BP:  135/85 mmHg,   HR: 72 bpm,   Temp: 37.1°C,   SpO2: 98% on room air.\n\n\n"
        "MEDICATIONS:\n"
        "Aspirin 81mg PO daily, Metoprolol 25mg BID.\n"
        "No acute cardiopulmonary disease noted.\n"
    )
    cleaned, txs = ClinicalTextCleaner.clean(messy_text)
    assert "\r" not in cleaned
    assert "\x00" not in cleaned
    assert "135/85 mmHg" in cleaned
    assert "37.1°C" in cleaned
    assert "98%" in cleaned
    assert "Aspirin 81mg PO daily" in cleaned
    assert "No acute cardiopulmonary disease noted" in cleaned
    # Ensure paragraph spacing is preserved
    assert "CHIEF COMPLAINT:\nPatient presents" in cleaned


def test_clinical_text_cleaner_empty_or_corrupted() -> None:
    """Verify empty or severely corrupted text is detected."""
    assert ClinicalTextCleaner.is_corrupted_or_empty("") is True
    assert ClinicalTextCleaner.is_corrupted_or_empty("    \n\t  ") is True
    corrupted = "\x00" * 50 + "hello"
    assert ClinicalTextCleaner.is_corrupted_or_empty(corrupted) is True


# ==============================================================================
# Demographic Normalizer Tests
# ==============================================================================

def test_demographic_normalizer_complete_patient() -> None:
    """Verify full patient normalization produces canonical representation and audit records."""
    raw = {
        "mrn": "  0010492  ",
        "first_name": "  Alexander  ",
        "last_name": " Hamilton ",
        "dob": "1994-01-11",
        "gender": "M",
        "phone": "555-0199",
    }
    patient, audits, issues = DemographicNormalizer.normalize_patient(
        raw_data=raw,
        source_system="hospital_one",
        job_id="job-test-123",
    )
    assert len(issues) == 0
    assert patient is not None
    assert patient.mrn == "0010492"
    assert patient.first_name == "Alexander"
    assert patient.last_name == "Hamilton"
    assert patient.date_of_birth == "1994-01-11"
    assert patient.administrative_gender == "male"
    assert len(audits) >= 3  # MRN trimmed, first name trimmed, last name trimmed, gender normalized


def test_demographic_normalizer_missing_mandatory() -> None:
    """Verify patient is rejected if mandatory MRN or names are missing."""
    raw_missing_mrn = {
        "first_name": "Thomas",
        "last_name": "Jefferson",
        "dob": "1990-04-13",
    }
    patient, audits, issues = DemographicNormalizer.normalize_patient(
        raw_data=raw_missing_mrn,
        source_system="hospital_one",
        job_id="job-test-123",
    )
    assert patient is None
    assert any(iss["field"] == "mrn" for iss in issues)
