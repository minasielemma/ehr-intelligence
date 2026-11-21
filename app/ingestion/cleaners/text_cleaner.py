"""Conservative clinical document text cleaner.

Sanitizes narrative text while strictly preserving clinical semantics, units,
dosages, negative findings, and section structure.
"""

import re
from typing import List, Tuple


class ClinicalTextCleaner:
    """Conservative clinical document sanitizer that avoids altering clinical meaning."""

    CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    
    INLINE_WHITESPACE_REGEX = re.compile(r"[^\S\r\n]+")
    
    EXCESSIVE_NEWLINES_REGEX = re.compile(r"\n{3,}")

    @classmethod
    def clean(cls, text: str) -> Tuple[str, List[str]]:
        """Clean clinical text conservatively, returning cleaned string and list of applied transformations.
        
        Preserves:
        - Numerical values and ranges (e.g. 120/80, 0.05, 3.5-4.2)
        - Medical units and symbols (<, >, =, +, -, %, ±, °, mg/dL, mmHg)
        - Negative assertions (e.g. "No acute distress", "denies chest pain")
        - Clinical abbreviations (e.g. BID, TID, PRN, WNL, SOB)
        - Meaningful paragraph and section boundaries
        """
        if text is None:
            return "", []

        transformations: List[str] = []
        cleaned = text

        if "\r" in cleaned:
            cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
            transformations.append("LINE_ENDINGS_NORMALIZED")

        if cls.CONTROL_CHAR_REGEX.search(cleaned):
            cleaned = cls.CONTROL_CHAR_REGEX.sub("", cleaned)
            transformations.append("CONTROL_CHARS_STRIPPED")

        lines = cleaned.split("\n")
        normalized_lines = []
        trailing_modified = False
        inline_modified = False

        for line in lines:
            trimmed_line = line.rstrip()
            if trimmed_line != line:
                trailing_modified = True
            
            collapsed_line = cls.INLINE_WHITESPACE_REGEX.sub(" ", trimmed_line)
            if collapsed_line != trimmed_line:
                inline_modified = True
            
            normalized_lines.append(collapsed_line)

        cleaned = "\n".join(normalized_lines)
        if trailing_modified:
            transformations.append("LINE_TRAILING_WHITESPACE_TRIMMED")
        if inline_modified:
            transformations.append("INLINE_WHITESPACE_COLLAPSED")

        if cls.EXCESSIVE_NEWLINES_REGEX.search(cleaned):
            cleaned = cls.EXCESSIVE_NEWLINES_REGEX.sub("\n\n", cleaned)
            transformations.append("PARAGRAPH_SPACING_NORMALIZED")

        final_cleaned = cleaned.strip()
        if final_cleaned != cleaned:
            cleaned = final_cleaned
            transformations.append("DOCUMENT_BOUNDARIES_TRIMMED")

        return cleaned, transformations

    @classmethod
    def is_corrupted_or_empty(cls, text: str) -> bool:
        """Check if text is empty, purely whitespace, or severely corrupted with null bytes."""
        if not text or not text.strip():
            return True
        control_chars_count = len(cls.CONTROL_CHAR_REGEX.findall(text))
        if control_chars_count > 0 and (control_chars_count / max(len(text), 1)) > 0.10:
            return True
        return False
