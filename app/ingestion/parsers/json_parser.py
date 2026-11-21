"""JSON EHR parser supporting heterogeneous, nested, and consolidated multi-domain structures."""

import json
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, TextIO, Union

from app.core.exceptions import ValidationException
from app.ingestion.parsers.base import BaseParser
from app.schemas.canonical import MappingProfile, RawRecord


def resolve_nested_key(data: Dict[str, Any], path: Optional[str]) -> Any:
    """Retrieve value from a nested dictionary using dot-notation path."""
    if not path or not data:
        return None
    keys = path.split(".")
    curr: Any = data
    for k in keys:
        if isinstance(curr, dict) and k in curr:
            curr = curr[k]
        else:
            return None
    return curr


class JSONParser(BaseParser):
    """Parser for heterogeneous and consolidated multi-dataset JSON EHR records."""

    NESTED_DOMAIN_KEYS = {
        "encounters": "encounters",
        "visits": "encounters",
        "conditions": "conditions",
        "diagnoses": "conditions",
        "observations": "observations",
        "vitals": "observations",
        "labs": "observations",
        "medication_requests": "medication_requests",
        "medications": "medication_requests",
        "prescriptions": "medication_requests",
        "procedures": "procedures",
        "allergies": "allergies",
        "immunizations": "immunizations",
        "coverages": "coverages",
        "insurance": "coverages",
        "claims": "claims",
        "care_plans": "care_plans",
        "consents": "consents",
        "documents": "documents",
        "clinical_notes": "documents",
    }

    def parse(
        self,
        stream_or_data: Union[str, bytes, TextIO, BinaryIO],
        source_system: str = "generic_ehr",
        mapping_profile: Optional[MappingProfile] = None,
    ) -> Iterator[RawRecord]:
        """Parse JSON EHR export into RawRecords.
        
        Handles flat arrays of records, wrapped dicts, and consolidated multi-dataset exports.
        """
        mapping = mapping_profile or MappingProfile(source_system=source_system)

        try:
            if isinstance(stream_or_data, bytes):
                raw_obj = json.loads(stream_or_data.decode("utf-8"))
            elif isinstance(stream_or_data, str):
                raw_obj = json.loads(stream_or_data)
            elif hasattr(stream_or_data, "read"):
                content = stream_or_data.read()
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
                raw_obj = json.loads(content)
            else:
                raw_obj = stream_or_data
        except Exception as exc:
            raise ValidationException(
                message="Malformed JSON input: unable to parse syntax",
                details={"error": str(exc)},
            )

        if isinstance(raw_obj, dict):
            has_domains = any(
                k in raw_obj and isinstance(raw_obj[k], list)
                for k in ["organizations", "practitioners", "patients", "encounters"]
            )
            if has_domains:
                yield from self._parse_consolidated(raw_obj, source_system, mapping)
                return

        records_list: List[Any] = []
        if isinstance(raw_obj, list):
            records_list = raw_obj
        elif isinstance(raw_obj, dict):
            for container_key in ["records", "patients", "items", "data", "results", "entry"]:
                if container_key in raw_obj and isinstance(raw_obj[container_key], list):
                    records_list = raw_obj[container_key]
                    break
            if not records_list:
                records_list = [raw_obj]
        else:
            raise ValidationException(
                message="Invalid JSON structure: Root must be a JSON object or array",
                details={"type": type(raw_obj).__name__},
            )

        for idx, item in enumerate(records_list, start=1):
            if not isinstance(item, dict):
                continue
            yield from self._parse_record_item(item, source_system, mapping, idx)

    def _parse_consolidated(
        self,
        root: Dict[str, Any],
        source_system: str,
        mapping: MappingProfile,
    ) -> Iterator[RawRecord]:
        """Process consolidated JSON with top-level organizations, practitioners, and patients."""
        seq = 0
        
        for org in root.get("organizations", []):
            if isinstance(org, dict):
                seq += 1
                yield RawRecord(
                    source_record_id=org.get("id") or str(seq),
                    source_system=source_system,
                    source_format="json",
                    raw_patient={},
                    raw_document=org,
                    metadata={"domain": "organizations", "entity": org, "record_type": "organization"},
                    line_number=seq,
                )

        for prac in root.get("practitioners", []):
            if isinstance(prac, dict):
                seq += 1
                yield RawRecord(
                    source_record_id=prac.get("id") or str(seq),
                    source_system=source_system,
                    source_format="json",
                    raw_patient={},
                    raw_document=prac,
                    metadata={"domain": "practitioners", "entity": prac, "record_type": "practitioner"},
                    line_number=seq,
                )

        patients_list = root.get("patients") or root.get("records") or []
        for pat in patients_list:
            if isinstance(pat, dict):
                seq += 1
                yield from self._parse_record_item(pat, source_system, mapping, seq)

    def _parse_record_item(
        self,
        item: Dict[str, Any],
        source_system: str,
        mapping: MappingProfile,
        idx: int,
    ) -> Iterator[RawRecord]:
        """Parse a single patient/clinical dictionary item, unpacking any nested clinical arrays."""
        patient_data = item.get("patient") or item.get("demographics") or item
        if not isinstance(patient_data, dict):
            patient_data = item

        resolved_patient: Dict[str, Any] = dict(patient_data)
        for field_name in [
            mapping.mrn_field,
            mapping.first_name_field,
            mapping.middle_name_field,
            mapping.last_name_field,
            mapping.dob_field,
            mapping.gender_field,
            mapping.patient_id_field,
        ]:
            if field_name and "." in field_name:
                val = resolve_nested_key(item, field_name)
                if val is not None:
                    resolved_patient[field_name] = val

        source_rec_id = (
            item.get("record_id")
            or item.get("id")
            or resolve_nested_key(item, "metadata.id")
            or str(idx)
        )
        patient_source_id = resolved_patient.get("mrn") or resolved_patient.get("patient_id") or source_rec_id

        clinical_content = None
        if mapping.content_field:
            clinical_content = resolve_nested_key(item, mapping.content_field) or item.get(mapping.content_field)
        if not clinical_content:
            clinical_content = (
                item.get("clinical_note")
                or item.get("note")
                or item.get("report")
                or item.get("text")
                or item.get("narrative")
            )

        record_type = (
            item.get(mapping.record_type_field or "record_type")
            or item.get("type")
            or item.get("document_type")
            or "clinical_record"
        )

        record_date = (
            item.get(mapping.record_date_field or "record_date")
            or item.get("date")
            or item.get("encounter_date")
            or item.get("timestamp")
        )

        metadata: Dict[str, Any] = {
            "original_keys": list(item.keys()),
            "record_type": str(record_type),
            "record_date": str(record_date) if record_date else None,
            "domain": "patients",
        }
        if "metadata" in item and isinstance(item["metadata"], dict):
            metadata.update(item["metadata"])

        yield RawRecord(
            source_record_id=str(source_rec_id) if source_rec_id else None,
            source_system=source_system,
            source_format="json",
            raw_patient=resolved_patient,
            raw_document=clinical_content or item,
            metadata=metadata,
            line_number=idx,
        )

        for key, domain in self.NESTED_DOMAIN_KEYS.items():
            if key in item and isinstance(item[key], list):
                for sub_idx, sub_item in enumerate(item[key], start=1):
                    if not isinstance(sub_item, dict):
                        continue
                    sub_entity = dict(sub_item)
                    if "patient_id" not in sub_entity and "patient_source_id" not in sub_entity:
                        sub_entity["patient_source_id"] = str(patient_source_id)

                    sub_id = sub_entity.get("id") or f"{source_rec_id}_{domain}_{sub_idx}"

                    if domain == "encounters":
                        for enc_sub_key, enc_sub_domain in self.NESTED_DOMAIN_KEYS.items():
                            if enc_sub_key != "encounters" and enc_sub_key in sub_entity and isinstance(sub_entity[enc_sub_key], list):
                                for child_idx, child_item in enumerate(sub_entity[enc_sub_key], start=1):
                                    if isinstance(child_item, dict):
                                        child_entity = dict(child_item)
                                        child_entity["patient_source_id"] = str(patient_source_id)
                                        child_entity["encounter_source_id"] = str(sub_id)
                                        child_rec_id = child_entity.get("id") or f"{sub_id}_{enc_sub_domain}_{child_idx}"
                                        yield RawRecord(
                                            source_record_id=str(child_rec_id),
                                            source_system=source_system,
                                            source_format="json",
                                            raw_patient=resolved_patient,
                                            raw_document=child_entity,
                                            metadata={
                                                "domain": enc_sub_domain,
                                                "entity": child_entity,
                                                "record_type": enc_sub_domain,
                                                "encounter_source_id": str(sub_id),
                                            },
                                            line_number=idx,
                                        )

                    yield RawRecord(
                        source_record_id=str(sub_id),
                        source_system=source_system,
                        source_format="json",
                        raw_patient=resolved_patient,
                        raw_document=sub_entity,
                        metadata={
                            "domain": domain,
                            "entity": sub_entity,
                            "record_type": domain,
                            "encounter_source_id": sub_entity.get("encounter_id") or sub_entity.get("encounter_source_id"),
                        },
                        line_number=idx,
                    )
