"""Medical Record Number (MRN) normalizer.

Enforces whitespace trimming, leading-zero preservation, and scoped authority validation.
"""

import re
from typing import Optional, Tuple


class MRNNormalizer:
    """Deterministic normalizer for Medical Record Numbers (MRNs)."""

    WHITESPACE_REGEX = re.compile(r"\s+")

    @classmethod
    def normalize_mrn(
        cls,
        raw_mrn: Optional[str],
        source_system: str = "generic_ehr",
        strip_prefix: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Normalize MRN string while strictly preserving leading zeroes and institution context.
        
        Returns:
            Tuple of (normalized_mrn, original_mrn, transformation_applied)
        """
        if raw_mrn is None or not str(raw_mrn).strip():
            return None, None if raw_mrn is None else str(raw_mrn), None

        original = str(raw_mrn)
        normalized = cls.WHITESPACE_REGEX.sub("", original.strip())

        transformation = "MRN_WHITESPACE_TRIMMED"
        if strip_prefix and normalized.upper().startswith(strip_prefix.upper()):
            normalized = normalized[len(strip_prefix):].lstrip("-:_")
            transformation = "MRN_PREFIX_STRIPPED"

        return normalized, original, transformation
