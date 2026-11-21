"""Deterministic administrative gender normalizer.

Converts heterogeneous gender codes into canonical HL7 FHIR administrative gender values
without inferring gender from names or demographics.
"""

from typing import Optional, Tuple


class GenderNormalizer:
    """Deterministic mapper for administrative gender."""

    MALE_SET = {"M", "MALE", "1", "BOY", "MAN"}
    FEMALE_SET = {"F", "FEMALE", "2", "GIRL", "WOMAN"}
    OTHER_SET = {"O", "OTHER", "NON-BINARY", "NONBINARY", "X", "3"}
    UNKNOWN_SET = {"U", "UNKNOWN", "UNSPECIFIED", "DECLINED", "UNDETERMINED", "0", "N/A", "NA", ""}

    @classmethod
    def normalize_gender(cls, raw_gender: Optional[str]) -> Tuple[str, Optional[str], Optional[str]]:
        """Map raw administrative gender to canonical FHIR representation ('male', 'female', 'other', 'unknown').
        
        Returns:
            Tuple of (canonical_value, original_value, transformation_applied)
        """
        if raw_gender is None:
            return "unknown", None, "GENDER_DEFAULT_UNKNOWN"

        original = str(raw_gender)
        cleaned = original.strip().upper()

        if cleaned in cls.MALE_SET:
            return "male", original, "GENDER_NORMALIZED_MALE"
        elif cleaned in cls.FEMALE_SET:
            return "female", original, "GENDER_NORMALIZED_FEMALE"
        elif cleaned in cls.OTHER_SET:
            return "other", original, "GENDER_NORMALIZED_OTHER"
        elif cleaned in cls.UNKNOWN_SET:
            return "unknown", original, "GENDER_NORMALIZED_UNKNOWN"
        else:
            return "unknown", original, "GENDER_UNRECOGNIZED_MAPPED_UNKNOWN"
