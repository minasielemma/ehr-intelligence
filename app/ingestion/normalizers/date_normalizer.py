"""Deterministic date and timestamp normalizer for EHR clinical records and demographics.

Supports ISO 8601, US, and UK date formats, handles timezone-aware timestamps,
and strictly detects and flags ambiguous dates without guessing.
"""

from datetime import datetime, timezone
import re
from typing import Optional


class DateNormalizationResult:
    """Result container for date normalization."""

    def __init__(
        self,
        original_value: str,
        normalized_value: Optional[str] = None,
        is_valid: bool = True,
        is_ambiguous: bool = False,
        error_message: Optional[str] = None,
        applied_format: Optional[str] = None,
    ) -> None:
        self.original_value = original_value
        self.normalized_value = normalized_value
        self.is_valid = is_valid
        self.is_ambiguous = is_ambiguous
        self.error_message = error_message
        self.applied_format = applied_format


class DateNormalizer:
    """Normalizes heterogeneous healthcare date strings into canonical ISO 8601 representations."""

    ISO_DATE_REGEX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
    
    SLASH_DATE_REGEX = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
    
    YEAR_FIRST_REGEX = re.compile(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$")

    MONTH_NAMES = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    TEXT_DMY_REGEX = re.compile(r"^(\d{1,2})[\s/.-]+([A-Za-z]+)[\s/.-]+(\d{4})$")
    TEXT_MDY_REGEX = re.compile(r"^([A-Za-z]+)[\s/.-]+(\d{1,2})(?:st|nd|rd|th)?(?:,)?[\s/.-]+(\d{4})$")
    TEXT_YMD_REGEX = re.compile(r"^(\d{4})[\s/.-]+([A-Za-z]+)[\s/.-]+(\d{1,2})(?:st|nd|rd|th)?$")

    @classmethod
    def normalize_date(
        cls,
        date_str: Optional[str],
        format_hint: Optional[str] = None,
    ) -> DateNormalizationResult:
        """Normalize date strings into canonical YYYY-MM-DD.
        
        Strictly rejects ambiguous dates (e.g. 03/04/2020) unless a format_hint is specified.
        """
        if not date_str or not str(date_str).strip():
            return DateNormalizationResult(
                original_value="" if date_str is None else str(date_str),
                is_valid=False,
                error_message="Empty date value provided",
            )

        raw = str(date_str).strip()

        iso_match = cls.ISO_DATE_REGEX.match(raw)
        if iso_match:
            year, month, day = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
            try:
                dt = datetime(year, month, day)
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=dt.strftime("%Y-%m-%d"),
                    is_valid=True,
                    applied_format="ISO_8601_DATE",
                )
            except ValueError as e:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Invalid calendar date: {e}",
                )

        yf_match = cls.YEAR_FIRST_REGEX.match(raw)
        if yf_match:
            year, month, day = int(yf_match.group(1)), int(yf_match.group(2)), int(yf_match.group(3))
            try:
                dt = datetime(year, month, day)
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=dt.strftime("%Y-%m-%d"),
                    is_valid=True,
                    applied_format="YYYY/MM/DD",
                )
            except ValueError as e:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Invalid calendar date: {e}",
                )

        dmy_text = cls.TEXT_DMY_REGEX.match(raw)
        if dmy_text:
            day_str, month_str, year_str = dmy_text.group(1), dmy_text.group(2), dmy_text.group(3)
            month_num = cls.MONTH_NAMES.get(month_str.lower())
            if not month_num:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Unrecognized month name: '{month_str}'",
                )
            try:
                dt = datetime(int(year_str), month_num, int(day_str))
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=dt.strftime("%Y-%m-%d"),
                    is_valid=True,
                    applied_format="TEXT_DD_MON_YYYY",
                )
            except ValueError as e:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Invalid calendar date: {e}",
                )

        mdy_text = cls.TEXT_MDY_REGEX.match(raw)
        if mdy_text:
            month_str, day_str, year_str = mdy_text.group(1), mdy_text.group(2), mdy_text.group(3)
            month_num = cls.MONTH_NAMES.get(month_str.lower())
            if not month_num:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Unrecognized month name: '{month_str}'",
                )
            try:
                dt = datetime(int(year_str), month_num, int(day_str))
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=dt.strftime("%Y-%m-%d"),
                    is_valid=True,
                    applied_format="TEXT_MON_DD_YYYY",
                )
            except ValueError as e:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Invalid calendar date: {e}",
                )

        ymd_text = cls.TEXT_YMD_REGEX.match(raw)
        if ymd_text:
            year_str, month_str, day_str = ymd_text.group(1), ymd_text.group(2), ymd_text.group(3)
            month_num = cls.MONTH_NAMES.get(month_str.lower())
            if not month_num:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Unrecognized month name: '{month_str}'",
                )
            try:
                dt = datetime(int(year_str), month_num, int(day_str))
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=dt.strftime("%Y-%m-%d"),
                    is_valid=True,
                    applied_format="TEXT_YYYY_MON_DD",
                )
            except ValueError as e:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Invalid calendar date: {e}",
                )

        slash_match = cls.SLASH_DATE_REGEX.match(raw)
        if slash_match:
            part_a = int(slash_match.group(1))
            part_b = int(slash_match.group(2))
            year = int(slash_match.group(3))

            if format_hint:
                hint_upper = format_hint.upper()
                if "MM/DD" in hint_upper or "MM-DD" in hint_upper:
                    month, day = part_a, part_b
                elif "DD/MM" in hint_upper or "DD-MM" in hint_upper:
                    day, month = part_a, part_b
                else:
                    return DateNormalizationResult(
                        original_value=raw,
                        is_valid=False,
                        error_message=f"Unrecognized date format hint: {format_hint}",
                    )
                try:
                    dt = datetime(year, month, day)
                    return DateNormalizationResult(
                        original_value=raw,
                        normalized_value=dt.strftime("%Y-%m-%d"),
                        is_valid=True,
                        applied_format=f"HINT_{hint_upper}",
                    )
                except ValueError as e:
                    return DateNormalizationResult(
                        original_value=raw,
                        is_valid=False,
                        error_message=f"Invalid calendar date for hint {format_hint}: {e}",
                    )

            if part_a <= 12 and part_b <= 12 and part_a != part_b:
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=None,
                    is_valid=False,
                    is_ambiguous=True,
                    error_message=(
                        f"Ambiguous date '{raw}': Cannot determine between MM/DD/YYYY "
                        f"and DD/MM/YYYY without a source mapping profile format hint."
                    ),
                )

            if part_a > 12 and part_b <= 12:
                day, month = part_a, part_b
                format_name = "DD/MM/YYYY"
            elif part_b > 12 and part_a <= 12:
                month, day = part_a, part_b
                format_name = "MM/DD/YYYY"
            elif part_a == part_b and part_a <= 12:
                month, day = part_a, part_b
                format_name = "SYMMETRIC_DATE"
            else:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Values out of range for date: {raw}",
                )

            try:
                dt = datetime(year, month, day)
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=dt.strftime("%Y-%m-%d"),
                    is_valid=True,
                    applied_format=format_name,
                )
            except ValueError as e:
                return DateNormalizationResult(
                    original_value=raw,
                    is_valid=False,
                    error_message=f"Invalid calendar date: {e}",
                )

        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return DateNormalizationResult(
                original_value=raw,
                normalized_value=dt.strftime("%Y-%m-%d"),
                is_valid=True,
                applied_format="ISO_8601_TIMESTAMP",
            )
        except Exception:
            pass

        return DateNormalizationResult(
            original_value=raw,
            is_valid=False,
            error_message=f"Unrecognized or unsupported date format: '{raw}'",
        )

    @classmethod
    def normalize_timestamp(
        cls,
        timestamp_str: Optional[str],
        format_hint: Optional[str] = None,
    ) -> DateNormalizationResult:
        """Normalize datetime timestamp string into canonical ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ)."""
        if not timestamp_str or not str(timestamp_str).strip():
            return DateNormalizationResult(
                original_value="" if timestamp_str is None else str(timestamp_str),
                is_valid=False,
                error_message="Empty timestamp value provided",
            )

        raw = str(timestamp_str).strip()

        date_res = cls.normalize_date(raw, format_hint=format_hint)
        if date_res.is_ambiguous:
            return date_res

        try:
            cleaned_raw = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_raw)
            if dt.tzinfo is not None:
                dt_utc = dt.astimezone(timezone.utc)
                iso_ts = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                iso_ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            return DateNormalizationResult(
                original_value=raw,
                normalized_value=iso_ts,
                is_valid=True,
                applied_format="ISO_8601_DATETIME",
            )
        except Exception:
            if date_res.is_valid and date_res.normalized_value:
                return DateNormalizationResult(
                    original_value=raw,
                    normalized_value=f"{date_res.normalized_value}T00:00:00Z",
                    is_valid=True,
                    applied_format="DATE_TO_TIMESTAMP_DEFAULT",
                )
            return DateNormalizationResult(
                original_value=raw,
                is_valid=False,
                error_message=f"Unable to parse timestamp: '{raw}'",
            )
