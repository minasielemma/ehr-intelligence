"""HL7 FHIR R4 parser supporting Bundles, NDJSON streams, and individual resources."""

import io
import json
from typing import Any, BinaryIO, Dict, Iterator, Optional, TextIO, Union

from app.core.exceptions import ValidationException
from app.core.logging import get_logger
from app.fhir.mapper import FHIRMapper
from app.fhir.validator import FHIRValidator
from app.ingestion.parsers.base import BaseParser
from app.schemas.canonical import MappingProfile, RawRecord

logger = get_logger(__name__)


class FHIRParser(BaseParser):
    """Parses HL7 FHIR R4 JSON Bundles, NDJSON streams, and individual resource payloads."""

    def _get_text_stream(self, stream_or_data: Union[str, bytes, TextIO, BinaryIO]) -> io.TextIOBase:
        """Convert input to text stream with utf-8 decoding fallback."""
        if isinstance(stream_or_data, str):
            return io.StringIO(stream_or_data)
        elif isinstance(stream_or_data, bytes):
            return io.StringIO(stream_or_data.decode("utf-8", errors="replace"))
        elif hasattr(stream_or_data, "read"):
            data = stream_or_data.read()
            if isinstance(data, bytes):
                return io.StringIO(data.decode("utf-8", errors="replace"))
            return io.StringIO(str(data))
        raise ValidationException("Unsupported input type for FHIR parsing")

    def parse(
        self,
        stream_or_data: Union[str, bytes, TextIO, BinaryIO],
        source_system: str = "fhir_r4",
        mapping_profile: Optional[MappingProfile] = None,
    ) -> Iterator[RawRecord]:
        """Stream or parse FHIR input into standardized RawRecord stream."""
        text_stream = self._get_text_stream(stream_or_data)

        first_char = ""
        while True:
            ch = text_stream.read(1)
            if not ch:
                break
            if not ch.isspace():
                first_char = ch
                break

        if not first_char:
            return

        text_stream.seek(0)
        first_line = text_stream.readline()
        text_stream.seek(0)
        is_ndjson = False
        try:
            parsed_first = json.loads(first_line.strip())
            if isinstance(parsed_first, dict) and parsed_first.get("resourceType") != "Bundle":
                second_line = text_stream.readline()
                second_line_val = text_stream.readline().strip()
                if second_line_val.startswith("{"):
                    is_ndjson = True
                text_stream.seek(0)
        except Exception:
            text_stream.seek(0)

        if is_ndjson:
            yield from self._parse_ndjson(text_stream, source_system)
        else:
            full_content = text_stream.read()
            try:
                root_obj = json.loads(full_content)
            except Exception as exc:
                text_stream.seek(0)
                try:
                    yield from self._parse_ndjson(text_stream, source_system)
                    return
                except Exception:
                    raise ValidationException(f"Invalid FHIR JSON syntax: {str(exc)}")

            if isinstance(root_obj, dict):
                res_type = root_obj.get("resourceType")
                if res_type == "Bundle":
                    yield from self._parse_bundle(root_obj, source_system)
                elif res_type:
                    yield from self._parse_single_resource(root_obj, source_system, line_num=1)
                elif "entry" in root_obj and isinstance(root_obj["entry"], list):
                    yield from self._parse_bundle(root_obj, source_system)
                else:
                    raise ValidationException(
                        f"Unrecognized FHIR root object: missing 'resourceType' or 'entry'"
                    )
            elif isinstance(root_obj, list):
                for idx, res_item in enumerate(root_obj, start=1):
                    if isinstance(res_item, dict):
                        yield from self._parse_single_resource(res_item, source_system, line_num=idx)
            else:
                raise ValidationException("Invalid FHIR payload: root must be JSON object or array")

    def _parse_bundle(self, bundle_dict: Dict[str, Any], source_system: str) -> Iterator[RawRecord]:
        """Parse all resource entries within a FHIR Bundle."""
        entries = bundle_dict.get("entry", [])
        for idx, entry in enumerate(entries, start=1):
            res = entry.get("resource")
            if not res or not isinstance(res, dict):
                continue
            yield from self._parse_single_resource(res, source_system, line_num=idx)

    def _parse_ndjson(self, stream: io.TextIOBase, source_system: str) -> Iterator[RawRecord]:
        """Stream NDJSON lines yielding a RawRecord for each resource."""
        line_num = 0
        for line in stream:
            line_num += 1
            line_str = line.strip()
            if not line_str:
                continue
            try:
                res_dict = json.loads(line_str)
            except Exception as exc:
                logger.warning("Skipping unparseable NDJSON line #%d: %s", line_num, exc)
                continue

            if isinstance(res_dict, dict):
                yield from self._parse_single_resource(res_dict, source_system, line_num=line_num)

    def _parse_single_resource(
        self,
        res_dict: Dict[str, Any],
        source_system: str,
        line_num: int = 1,
    ) -> Iterator[RawRecord]:
        """Validate, map, and emit a RawRecord for a single FHIR resource."""
        res_type = res_dict.get("resourceType", "Unknown")
        is_valid, validation_err = FHIRValidator.validate_resource(res_dict)

        domain, entity_dict = FHIRMapper.to_canonical_entity(res_dict, source_system=source_system)
        source_id = res_dict.get("id") or entity_dict.get("source_id") or str(line_num)
        raw_patient: Dict[str, Any] = {}
        if res_type == "Patient":
            raw_patient = {
                "mrn": entity_dict.get("mrn") or source_id,
                "first_name": entity_dict.get("first_name", "UNKNOWN"),
                "middle_name": entity_dict.get("middle_name"),
                "last_name": entity_dict.get("last_name", "UNKNOWN"),
                "dob": entity_dict.get("date_of_birth"),
                "gender": entity_dict.get("administrative_gender", "unknown"),
                "source_patient_id": source_id,
            }
        else:
            patient_ref = entity_dict.get("patient_source_id")
            if patient_ref:
                raw_patient = {
                    "mrn": patient_ref,
                    "patient_id": patient_ref,
                    "source_patient_id": patient_ref,
                }

        yield RawRecord(
            source_record_id=str(source_id),
            source_system=source_system,
            source_format="fhir",
            raw_patient=raw_patient,
            raw_document=res_dict,
            metadata={
                "fhir_resource_type": res_type,
                "domain": domain,
                "entity": entity_dict,
                "is_fhir_valid": is_valid,
                "fhir_validation_error": validation_err,
                "line_number": line_num,
                "record_type": res_type.lower(),
            },
            line_number=line_num,
        )
