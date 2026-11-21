"""Conservative plain-text clinical document parser with structured header recognition."""

import re
from typing import BinaryIO, Iterator, Optional, TextIO, Union

from app.ingestion.parsers.base import BaseParser
from app.schemas.canonical import MappingProfile, RawRecord


class TextParser(BaseParser):
    """Parses unstructured clinical documents, extracting demographic headers conservatively."""

    PATIENT_NAME_REGEX = re.compile(
        r"(?:PATIENT(?:\s+NAME)?|NAME)\s*[:=-]\s*([^\n\r,]+)(?:,\s*([^\n\r]+))?",
        re.IGNORECASE,
    )
    MRN_REGEX = re.compile(
        r"(?:MRN|MED(?:ICAL)?\s+REC(?:ORD)?\s*(?:NO|NUM|NUMBER)?|PATIENT\s+ID)\s*[:=-]\s*([A-Za-z0-9_-]+)",
        re.IGNORECASE,
    )
    DOB_REGEX = re.compile(
        r"(?:DOB|DATE\s+OF\s+BIRTH|BIRTH\s*DATE)\s*[:=-]\s*([0-9A-Za-z/.-]+)",
        re.IGNORECASE,
    )
    GENDER_REGEX = re.compile(
        r"(?:GENDER|SEX)\s*[:=-]\s*([A-Za-z]+)",
        re.IGNORECASE,
    )
    DATE_REGEX = re.compile(
        r"(?:DATE|ENCOUNTER\s+DATE|SERVICE\s+DATE|RECORD\s+DATE)\s*[:=-]\s*([0-9A-Za-z/.-]+)",
        re.IGNORECASE,
    )
    DOC_TYPE_REGEX = re.compile(
        r"(?:TYPE|DOCUMENT\s+TYPE|TITLE|REPORT\s+TYPE)\s*[:=-]\s*([^\n\r]+)",
        re.IGNORECASE,
    )
    ENCOUNTER_REGEX = re.compile(
        r"(?:ENCOUNTER(?:\s+ID|\s+NO|\s+NUMBER)?|VISIT(?:\s+ID|\s+NO)?|ADM(?:ISSION)?(?:\s+ID)?)\s*[:=-]\s*([A-Za-z0-9_-]+)",
        re.IGNORECASE,
    )

    def parse(
        self,
        stream_or_data: Union[str, bytes, TextIO, BinaryIO],
        source_system: str = "generic_ehr",
        mapping_profile: Optional[MappingProfile] = None,
    ) -> Iterator[RawRecord]:
        """Parse raw clinical text document into a RawRecord without fabricating missing clinical data."""
        if isinstance(stream_or_data, bytes):
            content = stream_or_data.decode("utf-8", errors="replace")
        elif isinstance(stream_or_data, str):
            content = stream_or_data
        elif hasattr(stream_or_data, "read"):
            data = stream_or_data.read()
            if isinstance(data, bytes):
                content = data.decode("utf-8", errors="replace")
            else:
                content = str(data)
        else:
            content = str(stream_or_data)

        if not content.strip():
            return

        header_lines = content.split("\n")[:40]
        header_text = "\n".join(header_lines)

        first_name: Optional[str] = None
        last_name: Optional[str] = None
        mrn: Optional[str] = None
        dob: Optional[str] = None
        gender: Optional[str] = None
        record_date: Optional[str] = None
        record_type = "clinical_document"

        mrn_match = self.MRN_REGEX.search(header_text)
        if mrn_match:
            mrn = mrn_match.group(1).strip()

        name_match = self.PATIENT_NAME_REGEX.search(header_text)
        if name_match:
            part1 = name_match.group(1).strip()
            part2 = name_match.group(2).strip() if name_match.group(2) else None
            if part2:
                last_name = part1
                first_name = part2
            else:
                name_tokens = part1.split()
                if len(name_tokens) >= 2:
                    first_name = name_tokens[0]
                    last_name = " ".join(name_tokens[1:])
                elif len(name_tokens) == 1:
                    first_name = name_tokens[0]
                    last_name = "UNKNOWN"

        dob_match = self.DOB_REGEX.search(header_text)
        if dob_match:
            dob = dob_match.group(1).strip()

        gender_match = self.GENDER_REGEX.search(header_text)
        if gender_match:
            gender = gender_match.group(1).strip()

        date_match = self.DATE_REGEX.search(header_text)
        if date_match:
            record_date = date_match.group(1).strip()

        type_match = self.DOC_TYPE_REGEX.search(header_text)
        if type_match:
            record_type = type_match.group(1).strip()

        encounter_source_id: Optional[str] = None
        enc_match = self.ENCOUNTER_REGEX.search(header_text)
        if enc_match:
            encounter_source_id = enc_match.group(1).strip()

        raw_patient = {
            "mrn": mrn,
            "first_name": first_name,
            "last_name": last_name,
            "dob": dob,
            "gender": gender,
        }

        metadata = {
            "record_type": record_type,
            "record_date": record_date,
            "encounter_source_id": encounter_source_id,
            "has_recognized_header": bool(mrn or first_name or dob),
        }

        yield RawRecord(
            source_record_id=mrn or "txt_doc_1",
            source_system=source_system,
            source_format="text",
            raw_patient=raw_patient,
            raw_document=content,
            metadata=metadata,
            line_number=1,
        )
