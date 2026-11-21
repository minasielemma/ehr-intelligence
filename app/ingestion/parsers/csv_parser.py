"""Streaming, chunk-based CSV EHR parser supporting variable delimiters, quotes, and encodings."""

import csv
import io
from typing import BinaryIO, Dict, Iterator, List, Optional, TextIO, Union

from app.core.exceptions import ValidationException
from app.ingestion.parsers.base import BaseParser
from app.schemas.canonical import MappingProfile, RawRecord


class CSVParser(BaseParser):
    """Streaming CSV parser capable of processing large healthcare tabular records with bounded memory."""

    SUPPORTED_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]

    @classmethod
    def detect_delimiter(cls, sample: str) -> str:
        """Heuristically sniff CSV delimiter from text sample."""
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample, delimiters=",;\t|")
            return dialect.delimiter
        except Exception:
            counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
            best = max(counts, key=counts.get)
            return best if counts[best] > 0 else ","

    @classmethod
    def detect_domain_from_headers(cls, fieldnames: List[str]) -> str:
        """Inspect CSV header columns and detect the healthcare domain."""
        fn_set = {f.strip().lower() for f in fieldnames if f}

        if any(k in fn_set for k in ["provenance_id", "signature_status"]) or ("target_resource_type" in fn_set and "target_resource_id" in fn_set):
            return "provenances"

        if any(k in fn_set for k in ["admission_date", "discharge_date", "encounter_class", "visit_id", "reason_code"]):
            return "encounters"

        if any(k in fn_set for k in ["claim_id", "claim_type", "billable_period", "claim_amount"]) or ("total_amount" in fn_set and "currency" in fn_set):
            return "claims"

        if any(k in fn_set for k in ["condition_id", "diagnosis_code", "icd_code", "icd10", "onset_date"]) or ("clinical_status" in fn_set and "verification_status" in fn_set):
            return "conditions"

        if any(k in fn_set for k in ["observation_id", "loinc_code", "lab_code", "vital_sign", "value_quantity", "value_unit"]):
            return "observations"

        if any(k in fn_set for k in ["medication_request_id", "prescription_id", "rxnorm_code", "dosage", "medication_name"]):
            return "medication_requests"

        if any(k in fn_set for k in ["administration_id", "medication_administration_id", "administered_at"]):
            return "medication_administrations"

        if any(k in fn_set for k in ["procedure_id", "cpt_code", "performed_date", "surgery_id"]):
            return "procedures"

        if any(k in fn_set for k in ["allergy_id", "allergen", "criticality"]):
            return "allergies"

        if any(k in fn_set for k in ["immunization_id", "vaccine_code", "cvx_code", "lot_number"]):
            return "immunizations"

        if any(k in fn_set for k in ["policy_number", "payer_id", "subscriber_id", "insurance_id"]) or ("coverage_id" in fn_set and "total_amount" not in fn_set):
            return "coverages"

        if any(k in fn_set for k in ["organization_id", "org_id", "organization_name", "facility_id", "facility_name", "org_type"]):
            return "organizations"

        if any(k in fn_set for k in ["practitioner_id", "npi", "physician_id", "specialty", "license_number"]):
            return "practitioners"

        if any(k in fn_set for k in ["care_plan_id", "plan_title", "plan_category"]):
            return "care_plans"

        if any(k in fn_set for k in ["consent_id", "consent_policy", "consent_scope"]):
            return "consents"

        if any(k in fn_set for k in ["service_request_id", "order_code", "requisition_id"]):
            return "service_requests"

        if any(k in fn_set for k in ["diagnostic_report_id", "report_status", "specimen"]):
            return "diagnostic_reports"

        if any(k in fn_set for k in ["imaging_study_id", "modality", "dicom_uid", "series_number"]):
            return "imaging_studies"

        if any(k in fn_set for k in ["document_reference_id", "doc_ref_id", "doc_type"]):
            return "document_references"

        if "encounter_id" in fn_set and not any(k in fn_set for k in ["code", "display", "clinical_status"]):
            return "encounters"

        return "patients"

    def _get_text_stream(self, stream_or_data: Union[str, bytes, TextIO, BinaryIO]) -> io.TextIOBase:
        """Convert any supported input into an iterable text stream with encoding fallback."""
        if isinstance(stream_or_data, str):
            return io.StringIO(stream_or_data)
        elif isinstance(stream_or_data, bytes):
            for enc in self.SUPPORTED_ENCODINGS:
                try:
                    decoded = stream_or_data.decode(enc)
                    return io.StringIO(decoded)
                except UnicodeDecodeError:
                    continue
            return io.StringIO(stream_or_data.decode("utf-8", errors="replace"))
        elif hasattr(stream_or_data, "read"):
            if isinstance(getattr(stream_or_data, "mode", None), str) and "b" in stream_or_data.mode:
                raw_bytes = stream_or_data.read()
                return self._get_text_stream(raw_bytes)
            first_chunk = stream_or_data.read(1024)
            if isinstance(first_chunk, bytes):
                rest = stream_or_data.read()
                return self._get_text_stream(first_chunk + rest)
            else:
                if hasattr(stream_or_data, "seek"):
                    try:
                        stream_or_data.seek(0)
                        return stream_or_data  
                    except Exception:
                        pass
                return io.StringIO(first_chunk + stream_or_data.read())
        raise ValidationException("Unsupported input type for CSV parsing")

    def parse(
        self,
        stream_or_data: Union[str, bytes, TextIO, BinaryIO],
        source_system: str = "generic_ehr",
        mapping_profile: Optional[MappingProfile] = None,
    ) -> Iterator[RawRecord]:
        """Stream CSV lines in chunks and yield validated RawRecords."""
        mapping = mapping_profile or MappingProfile(source_system=source_system)
        text_stream = self._get_text_stream(stream_or_data)

        sample_lines: List[str] = []
        for _ in range(5):
            line = text_stream.readline()
            if not line:
                break
            sample_lines.append(line)

        if not sample_lines:
            return

        sample_text = "".join(sample_lines)
        delimiter = mapping.csv_delimiter or self.detect_delimiter(sample_text)

        import itertools
        chained_stream = itertools.chain(sample_lines, text_stream)
        reader = csv.DictReader(chained_stream, delimiter=delimiter)
        if not reader.fieldnames:
            return

        detected_domain = (
            getattr(mapping, "domain", None)
            or self.detect_domain_from_headers(list(reader.fieldnames))
        )

        field_map = {f.strip().lower(): f for f in reader.fieldnames if f}

        def get_col_value(row: Dict[str, str], target_col: Optional[str]) -> Optional[str]:
            if not target_col:
                return None
            target_lower = target_col.strip().lower()
            if target_lower in field_map:
                actual_col = field_map[target_lower]
                val = row.get(actual_col)
                return val.strip() if val else None
            if target_col in row and row[target_col]:
                return row[target_col].strip()
            return None

        line_num = 1
        for row in reader:
            line_num += 1
            if not any(row.values()):
                # Skip empty row
                continue

            mrn = (
                get_col_value(row, mapping.mrn_field)
                or get_col_value(row, "mrn")
                or get_col_value(row, "medical_record_number")
                or get_col_value(row, "patient_id")
            )
            fname = (
                get_col_value(row, mapping.first_name_field)
                or get_col_value(row, "first_name")
                or get_col_value(row, "firstname")
                or get_col_value(row, "given_name")
            )
            mname = (
                get_col_value(row, mapping.middle_name_field)
                or get_col_value(row, "middle_name")
                or get_col_value(row, "middlename")
            )
            lname = (
                get_col_value(row, mapping.last_name_field)
                or get_col_value(row, "last_name")
                or get_col_value(row, "lastname")
                or get_col_value(row, "family_name")
            )
            dob = (
                get_col_value(row, mapping.dob_field)
                or get_col_value(row, "dob")
                or get_col_value(row, "date_of_birth")
                or get_col_value(row, "birth_date")
            )
            gender = (
                get_col_value(row, mapping.gender_field)
                or get_col_value(row, "gender")
                or get_col_value(row, "sex")
            )

            record_date = (
                get_col_value(row, mapping.record_date_field)
                or get_col_value(row, "record_date")
                or get_col_value(row, "date")
                or get_col_value(row, "encounter_date")
            )
            record_type = (
                get_col_value(row, mapping.record_type_field)
                or get_col_value(row, "record_type")
                or get_col_value(row, "type")
                or "clinical_record"
            )
            content = (
                get_col_value(row, mapping.content_field)
                or get_col_value(row, "clinical_text")
                or get_col_value(row, "notes")
                or get_col_value(row, "note")
                or get_col_value(row, "narrative")
                or get_col_value(row, "report")
            )

            raw_patient = {
                "mrn": mrn,
                "first_name": fname,
                "middle_name": mname,
                "last_name": lname,
                "dob": dob,
                "gender": gender,
            }
            for k, v in row.items():
                if k and v and k.strip().lower() not in field_map:
                    raw_patient[k] = v

            source_rec_id = (
                get_col_value(row, "id")
                or get_col_value(row, "provenance_id")
                or get_col_value(row, f"{detected_domain.rstrip('s')}_id")
                or get_col_value(row, "record_id")
                or str(line_num)
            )

            yield RawRecord(
                source_record_id=source_rec_id,
                source_system=source_system,
                source_format="csv",
                raw_patient=raw_patient,
                raw_document=content or row,
                metadata={
                    "domain": detected_domain,
                    "line_number": line_num,
                    "record_date": record_date,
                    "record_type": record_type,
                    "raw_row": {k: v for k, v in row.items() if k},
                },
                line_number=line_num,
            )
