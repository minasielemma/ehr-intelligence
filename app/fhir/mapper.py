"""Bidirectional HL7 FHIR R4 mapper for clinical, administrative, and financial domains."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.core.logging import get_logger

logger = get_logger(__name__)


def extract_reference_id(ref: Optional[str]) -> Optional[str]:
    """Extract ID part from FHIR reference string (e.g. 'Patient/123' -> '123' or 'urn:uuid:xyz' -> 'xyz')."""
    if not ref:
        return None
    ref_str = str(ref).strip()
    if ref_str.startswith("urn:uuid:"):
        return ref_str[len("urn:uuid:"):]
    if "/" in ref_str:
        return ref_str.split("/")[-1]
    return ref_str


class FHIRMapper:
    """Maps between HL7 FHIR R4 resources and internal canonical healthcare entities."""

    # =========================================================================
    # Inbound: FHIR R4 Resource -> Internal Canonical Representation
    # =========================================================================

    @classmethod
    def to_canonical_entity(cls, fhir_res: Dict[str, Any], source_system: str = "fhir_r4") -> Tuple[str, Dict[str, Any]]:
        """Map any recognized FHIR R4 resource into an internal domain entity dict.
        
        Returns:
            Tuple of (domain_name: str, entity_dict: Dict[str, Any])
        """
        res_type = fhir_res.get("resourceType")
        source_id = fhir_res.get("id") or str(uuid.uuid4())

        if res_type == "Patient":
            return "patients", cls._map_patient(fhir_res, source_system, source_id)
        elif res_type == "Encounter":
            return "encounters", cls._map_encounter(fhir_res, source_system, source_id)
        elif res_type == "Condition":
            return "conditions", cls._map_condition(fhir_res, source_system, source_id)
        elif res_type == "Observation":
            return "observations", cls._map_observation(fhir_res, source_system, source_id)
        elif res_type == "MedicationRequest":
            return "medication_requests", cls._map_medication_request(fhir_res, source_system, source_id)
        elif res_type == "MedicationAdministration":
            return "medication_administrations", cls._map_medication_administration(fhir_res, source_system, source_id)
        elif res_type == "Procedure":
            return "procedures", cls._map_procedure(fhir_res, source_system, source_id)
        elif res_type == "AllergyIntolerance":
            return "allergies", cls._map_allergy(fhir_res, source_system, source_id)
        elif res_type == "Immunization":
            return "immunizations", cls._map_immunization(fhir_res, source_system, source_id)
        elif res_type == "Organization":
            return "organizations", cls._map_organization(fhir_res, source_system, source_id)
        elif res_type == "Practitioner":
            return "practitioners", cls._map_practitioner(fhir_res, source_system, source_id)
        elif res_type == "Coverage":
            return "coverages", cls._map_coverage(fhir_res, source_system, source_id)
        elif res_type == "Claim":
            return "claims", cls._map_claim(fhir_res, source_system, source_id)
        elif res_type == "CarePlan":
            return "care_plans", cls._map_care_plan(fhir_res, source_system, source_id)
        elif res_type == "Consent":
            return "consents", cls._map_consent(fhir_res, source_system, source_id)
        elif res_type == "ServiceRequest":
            return "service_requests", cls._map_service_request(fhir_res, source_system, source_id)
        elif res_type == "DiagnosticReport":
            return "diagnostic_reports", cls._map_diagnostic_report(fhir_res, source_system, source_id)
        elif res_type == "ImagingStudy":
            return "imaging_studies", cls._map_imaging_study(fhir_res, source_system, source_id)
        elif res_type == "DocumentReference":
            return "document_references", cls._map_document_reference(fhir_res, source_system, source_id)
        elif res_type == "Provenance":
            return "provenances", cls._map_provenance(fhir_res, source_system, source_id)
        else:
            return "unknown", {"resourceType": res_type, "source_id": source_id, "raw": fhir_res}

    @classmethod
    def _map_patient(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        mrn = source_id
        for ident in res.get("identifier", []):
            type_coding = ident.get("type", {}).get("coding", [{}])[0].get("code", "")
            if type_coding == "MR" or "mrn" in ident.get("system", "").lower():
                mrn = ident.get("value", mrn)
                break
            elif not mrn or mrn == source_id:
                mrn = ident.get("value", mrn)

        first_name = "UNKNOWN"
        last_name = "UNKNOWN"
        middle_name = None
        for name_obj in res.get("name", []):
            if "family" in name_obj:
                last_name = name_obj["family"]
            givens = name_obj.get("given", [])
            if givens:
                first_name = givens[0]
                if len(givens) > 1:
                    middle_name = givens[1]
            break

        return {
            "source_id": source_id,
            "source_system": source_system,
            "mrn": mrn,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "dob": res.get("birthDate"),
            "date_of_birth": res.get("birthDate"),
            "gender": res.get("gender", "unknown"),
            "administrative_gender": res.get("gender", "unknown"),
            "telecom": res.get("telecom"),
            "address": res.get("address"),
            "raw_resource": res,
        }

    @classmethod
    def _map_encounter(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        practitioner_ref = None
        for part in res.get("participant", []):
            ref = part.get("individual", {}).get("reference")
            if ref and ("Practitioner" in ref or not practitioner_ref):
                practitioner_ref = extract_reference_id(ref)
                break

        org_ref = extract_reference_id(res.get("serviceProvider", {}).get("reference"))
        enc_class = res.get("class", {}).get("code", "outpatient")
        period = res.get("period", {})

        reason_code = None
        reason_display = None
        reasons = res.get("reasonCode", [])
        if reasons:
            coding = reasons[0].get("coding", [{}])[0]
            reason_code = coding.get("code")
            reason_display = coding.get("display") or reasons[0].get("text")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "practitioner_source_id": practitioner_ref,
            "organization_source_id": org_ref,
            "encounter_class": enc_class.lower(),
            "class_code": enc_class,
            "status": res.get("status", "finished"),
            "start_date": period.get("start"),
            "start_time": period.get("start"),
            "end_date": period.get("end"),
            "end_time": period.get("end"),
            "reason_code": reason_code,
            "reason_display": reason_display,
            "raw_resource": res,
        }

    @classmethod
    def _map_condition(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        code_obj = res.get("code", {})
        coding = code_obj.get("coding", [{}])[0]
        code = coding.get("code", "UNKNOWN")
        system = coding.get("system", "http://hl7.org/fhir/sid/icd-10-cm")
        display = coding.get("display") or code_obj.get("text") or "Clinical Condition"

        clin_status = res.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "active")
        ver_status = res.get("verificationStatus", {}).get("coding", [{}])[0].get("code", "confirmed")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "code": code,
            "code_system": system,
            "display": display,
            "clinical_status": clin_status,
            "verification_status": ver_status,
            "onset_date": res.get("onsetDateTime") or res.get("onsetString"),
            "recorded_date": res.get("recordedDate"),
            "raw_resource": res,
        }

    @classmethod
    def _map_observation(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        code_obj = res.get("code", {})
        coding = code_obj.get("coding", [{}])[0]
        code = coding.get("code", "OBS")
        system = coding.get("system", "http://loinc.org")
        display = coding.get("display") or code_obj.get("text") or "Observation"

        categories = res.get("category", [])
        category = "vital-signs"
        if categories:
            cat_coding = categories[0].get("coding", [{}])[0]
            category = cat_coding.get("code", "vital-signs")

        value_numeric = None
        unit = None
        value_string = None
        if "valueQuantity" in res:
            value_numeric = float(res["valueQuantity"].get("value", 0))
            unit = res["valueQuantity"].get("unit") or res["valueQuantity"].get("code")
        elif "valueString" in res:
            value_string = res["valueString"]

        ref_range_low = None
        ref_range_high = None
        ref_ranges = res.get("referenceRange", [])
        if ref_ranges:
            low = ref_ranges[0].get("low", {}).get("value")
            high = ref_ranges[0].get("high", {}).get("value")
            if low is not None:
                ref_range_low = float(low)
            if high is not None:
                ref_range_high = float(high)

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "category": category,
            "code": code,
            "code_system": system,
            "display": display,
            "value_numeric": value_numeric,
            "value_quantity": value_numeric,
            "value_string": value_string,
            "unit": unit,
            "value_unit": unit,
            "reference_range_low": ref_range_low,
            "reference_range_high": ref_range_high,
            "status": res.get("status", "final"),
            "effective_date": res.get("effectiveDateTime") or res.get("effectivePeriod", {}).get("start"),
            "raw_resource": res,
        }

    @classmethod
    def _map_medication_request(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        practitioner_ref = extract_reference_id(res.get("requester", {}).get("reference"))

        med_concept = res.get("medicationCodeableConcept", {})
        coding = med_concept.get("coding", [{}])[0]
        code = coding.get("code", "MED")
        system = coding.get("system", "http://www.nlm.nih.gov/research/umls/rxnorm")
        display = coding.get("display") or med_concept.get("text") or "Medication"

        dosage_instruction = None
        dosages = res.get("dosageInstruction", [])
        if dosages:
            dosage_instruction = dosages[0].get("text")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "practitioner_source_id": practitioner_ref,
            "code": code,
            "code_system": system,
            "display": display,
            "status": res.get("status", "active"),
            "intent": res.get("intent", "order"),
            "dosage_instruction": dosage_instruction,
            "authored_on": res.get("authoredOn"),
            "raw_resource": res,
        }

    @classmethod
    def _map_medication_administration(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("context", {}).get("reference"))
        request_ref = extract_reference_id(res.get("request", {}).get("reference"))
        med_concept = res.get("medicationCodeableConcept", {})
        coding = med_concept.get("coding", [{}])[0]
        code = coding.get("code", "MED_ADMIN")
        display = coding.get("display") or med_concept.get("text") or "Administered Medication"

        dosage = res.get("dosage", {})
        qty = dosage.get("dose", {}).get("value")
        unit = dosage.get("dose", {}).get("unit")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "medication_request_source_id": request_ref,
            "code": code,
            "display": display,
            "status": res.get("status", "completed"),
            "dosage_administered": float(qty) if qty is not None else None,
            "unit": unit,
            "effective_date": res.get("effectiveDateTime"),
            "raw_resource": res,
        }

    @classmethod
    def _map_procedure(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        code_obj = res.get("code", {})
        coding = code_obj.get("coding", [{}])[0]
        code = coding.get("code", "PROC")
        system = coding.get("system", "http://snomed.info/sct")
        display = coding.get("display") or code_obj.get("text") or "Procedure"

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "code": code,
            "code_system": system,
            "display": display,
            "status": res.get("status", "completed"),
            "performed_date": res.get("performedDateTime") or res.get("performedPeriod", {}).get("start"),
            "raw_resource": res,
        }

    @classmethod
    def _map_allergy(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("patient", {}).get("reference"))
        code_obj = res.get("code", {})
        coding = code_obj.get("coding", [{}])[0]
        code = coding.get("code")
        display = coding.get("display") or code_obj.get("text") or "Allergy"
        clin_status = res.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "active")
        categories = res.get("category", [])
        category = categories[0] if categories else None

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "clinical_status": clin_status,
            "verification_status": res.get("verificationStatus", {}).get("coding", [{}])[0].get("code", "confirmed"),
            "allergy_type": res.get("type"),
            "category": category,
            "criticality": res.get("criticality"),
            "code": code,
            "display": display,
            "recorded_date": res.get("recordedDate"),
            "raw_resource": res,
        }

    @classmethod
    def _map_immunization(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("patient", {}).get("reference"))
        vaccine = res.get("vaccineCode", {})
        coding = vaccine.get("coding", [{}])[0]
        code = coding.get("code", "CVX")
        display = coding.get("display") or vaccine.get("text") or "Immunization"

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "status": res.get("status", "completed"),
            "vaccine_code": code,
            "vaccine_display": display,
            "occurrence_date": res.get("occurrenceDateTime") or res.get("occurrenceString"),
            "primary_source": res.get("primarySource", True),
            "lot_number": res.get("lotNumber"),
            "raw_resource": res,
        }

    @classmethod
    def _map_organization(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        return {
            "source_id": source_id,
            "source_system": source_system,
            "name": res.get("name", "Healthcare Organization"),
            "org_type": res.get("type", [{}])[0].get("coding", [{}])[0].get("code"),
            "address": res.get("address", [{}])[0] if res.get("address") else None,
            "phone": res.get("telecom", [{}])[0].get("value") if res.get("telecom") else None,
            "active": res.get("active", True),
            "raw_resource": res,
        }

    @classmethod
    def _map_practitioner(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        first_name = "Provider"
        last_name = "Unknown"
        for name_obj in res.get("name", []):
            if "family" in name_obj:
                last_name = name_obj["family"]
            if name_obj.get("given"):
                first_name = name_obj["given"][0]
            break

        npi = None
        for ident in res.get("identifier", []):
            if "npi" in ident.get("system", "").lower():
                npi = ident.get("value")
                break

        return {
            "source_id": source_id,
            "source_system": source_system,
            "npi": npi,
            "first_name": first_name,
            "last_name": last_name,
            "active": res.get("active", True),
            "raw_resource": res,
        }

    @classmethod
    def _map_coverage(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("beneficiary", {}).get("reference"))
        payer_name = res.get("payor", [{}])[0].get("display", "Health Insurance")
        period = res.get("period", {})

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "subscriber_id": res.get("subscriberId"),
            "status": res.get("status", "active"),
            "coverage_type": res.get("type", {}).get("coding", [{}])[0].get("code"),
            "payer_name": payer_name,
            "relationship_to_subscriber": res.get("relationship", {}).get("coding", [{}])[0].get("code", "self"),
            "period_start": period.get("start"),
            "period_end": period.get("end"),
            "raw_resource": res,
        }

    @classmethod
    def _map_claim(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("patient", {}).get("reference"))
        encounter_ref = None
        if "item" in res and res["item"]:
            encounter_ref = extract_reference_id(res["item"][0].get("encounter", [{}])[0].get("reference"))

        cov_ref = None
        if "insurance" in res and res["insurance"]:
            cov_ref = extract_reference_id(res["insurance"][0].get("coverage", {}).get("reference"))

        total = res.get("total", {})
        amount = float(total.get("value", 0.0))
        currency = total.get("currency", "USD")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "coverage_source_id": cov_ref,
            "claim_type": res.get("type", {}).get("coding", [{}])[0].get("code", "institutional"),
            "use": res.get("use", "claim"),
            "status": res.get("status", "active"),
            "total_amount": amount,
            "currency": currency,
            "created_date": res.get("created"),
            "raw_resource": res,
        }

    @classmethod
    def _map_care_plan(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        period = res.get("period", {})

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "status": res.get("status", "active"),
            "intent": res.get("intent", "plan"),
            "title": res.get("title", "Clinical Care Plan"),
            "description": res.get("description"),
            "period_start": period.get("start"),
            "period_end": period.get("end"),
            "raw_resource": res,
        }

    @classmethod
    def _map_consent(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("patient", {}).get("reference"))
        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "status": res.get("status", "active"),
            "scope": res.get("scope", {}).get("coding", [{}])[0].get("code", "treatment"),
            "date_time": res.get("dateTime"),
            "raw_resource": res,
        }

    @classmethod
    def _map_service_request(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        code_obj = res.get("code", {})
        coding = code_obj.get("coding", [{}])[0]
        code = coding.get("code", "SRV")
        display = coding.get("display") or code_obj.get("text") or "Service Request"

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "status": res.get("status", "active"),
            "intent": res.get("intent", "order"),
            "code": code,
            "display": display,
            "authored_on": res.get("authoredOn"),
            "raw_resource": res,
        }

    @classmethod
    def _map_diagnostic_report(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        srv_ref = None
        if "basedOn" in res and res["basedOn"]:
            srv_ref = extract_reference_id(res["basedOn"][0].get("reference"))

        code_obj = res.get("code", {})
        coding = code_obj.get("coding", [{}])[0]
        code = coding.get("code", "REPORT")
        display = coding.get("display") or code_obj.get("text") or "Diagnostic Report"

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "service_request_source_id": srv_ref,
            "status": res.get("status", "final"),
            "category": "LAB",
            "code": code,
            "display": display,
            "effective_date": res.get("effectiveDateTime"),
            "conclusion": res.get("conclusion"),
            "raw_resource": res,
        }

    @classmethod
    def _map_imaging_study(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = extract_reference_id(res.get("encounter", {}).get("reference"))
        modality = "CT"
        if "modality" in res and res["modality"]:
            modality = res["modality"][0].get("code", "CT")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "modality": modality,
            "description": res.get("description"),
            "started_date": res.get("started"),
            "number_of_series": res.get("numberOfSeries", 1),
            "number_of_instances": res.get("numberOfInstances", 1),
            "raw_resource": res,
        }

    @classmethod
    def _map_document_reference(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        patient_ref = extract_reference_id(res.get("subject", {}).get("reference"))
        encounter_ref = None
        if "context" in res:
            for enc_ref in res["context"].get("encounter", []):
                encounter_ref = extract_reference_id(enc_ref.get("reference"))
                break

        doc_type = res.get("type", {}).get("coding", [{}])[0].get("code", "clinical_note")
        content_text = None
        for content_item in res.get("content", []):
            attachment = content_item.get("attachment", {})
            if "data" in attachment:
                import base64
                try:
                    content_text = base64.b64decode(attachment["data"]).decode("utf-8")
                except Exception:
                    content_text = attachment["data"]
            elif "url" in attachment:
                content_text = attachment["url"]

        return {
            "source_id": source_id,
            "source_system": source_system,
            "patient_source_id": patient_ref,
            "encounter_source_id": encounter_ref,
            "status": res.get("status", "current"),
            "doc_type": doc_type,
            "description": res.get("description"),
            "content_text": content_text,
            "date": res.get("date"),
            "raw_resource": res,
        }

    @classmethod
    def _map_provenance(cls, res: Dict[str, Any], source_system: str, source_id: str) -> Dict[str, Any]:
        target_ref = res.get("target", [{}])[0].get("reference", "Unknown/0")
        target_type = "Resource"
        target_id = "0"
        if "/" in target_ref:
            parts = target_ref.split("/")
            target_type = parts[0]
            target_id = parts[1]

        activity = res.get("activity", {}).get("coding", [{}])[0].get("code", "CREATE")
        agent_name = None
        agent_role = None
        if res.get("agent"):
            agent_name = res["agent"][0].get("who", {}).get("display")
            roles = res["agent"][0].get("role", [])
            if roles:
                agent_role = roles[0].get("coding", [{}])[0].get("code")

        return {
            "source_id": source_id,
            "source_system": source_system,
            "target_resource_type": target_type,
            "target_resource_id": target_id,
            "recorded_at": res.get("recorded"),
            "activity": activity,
            "agent_name": agent_name,
            "agent_role": agent_role,
            "raw_resource": res,
        }

    @classmethod
    def to_fhir_patient(
        cls, patient: Any, base_system_url: str = "http://hospital.smarthealth.org"
    ) -> Dict[str, Any]:
        """Map canonical patient intermediate representation into an HL7 FHIR R4 Patient resource."""
        is_obj = hasattr(patient, "mrn")

        p_id = getattr(patient, "id", None) if is_obj else patient.get("id")
        p_id = str(p_id) if p_id else str(uuid.uuid4())

        mrn = getattr(patient, "mrn", None) if is_obj else patient.get("mrn")
        mrn = str(mrn).strip() if mrn else "UNKNOWN_MRN"

        first_name = (getattr(patient, "first_name", "") if is_obj else patient.get("first_name", "")) or ""
        middle_name = getattr(patient, "middle_name", None) if is_obj else patient.get("middle_name")
        last_name = (getattr(patient, "last_name", "") if is_obj else patient.get("last_name", "")) or ""

        givens = [first_name.strip()] if first_name.strip() else []
        if middle_name and str(middle_name).strip():
            givens.append(str(middle_name).strip())

        raw_gender = (getattr(patient, "administrative_gender", "") if is_obj else patient.get("administrative_gender", "")) or "unknown"
        norm_gender = str(raw_gender).lower().strip()
        if norm_gender in ["m", "male", "1"]:
            gender = "male"
        elif norm_gender in ["f", "female", "2"]:
            gender = "female"
        elif norm_gender in ["o", "other"]:
            gender = "other"
        else:
            gender = "unknown"

        dob = getattr(patient, "date_of_birth", None) if is_obj else patient.get("date_of_birth")
        birth_date = None
        if dob:
            dob_str = str(dob).strip()
            if "T" in dob_str:
                dob_str = dob_str.split("T")[0]
            elif " " in dob_str:
                dob_str = dob_str.split(" ")[0]
            birth_date = dob_str

        identifiers = [
            {
                "use": "usual",
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "MR",
                            "display": "Medical Record Number",
                        }
                    ],
                    "text": "MRN",
                },
                "system": f"{base_system_url}/mrn",
                "value": mrn,
            }
        ]

        source_pat_id = getattr(patient, "source_patient_id", None) if is_obj else patient.get("source_patient_id")
        if source_pat_id and str(source_pat_id) != mrn:
            identifiers.append({
                "use": "secondary",
                "system": f"{base_system_url}/patient-id",
                "value": str(source_pat_id),
            })

        fhir_patient: Dict[str, Any] = {
            "resourceType": "Patient",
            "id": p_id,
            "active": True,
            "identifier": identifiers,
            "name": [
                {
                    "use": "official",
                    "family": last_name.strip() if last_name.strip() else "UNKNOWN",
                    "given": givens if givens else ["UNKNOWN"],
                }
            ],
            "gender": gender,
        }

        if birth_date:
            fhir_patient["birthDate"] = birth_date

        contact = getattr(patient, "contact_info", None) if is_obj else patient.get("contact_info")
        if isinstance(contact, dict):
            telecoms = []
            if contact.get("phone"):
                telecoms.append({"system": "phone", "value": str(contact["phone"]), "use": "home"})
            if contact.get("email"):
                telecoms.append({"system": "email", "value": str(contact["email"]), "use": "home"})
            if telecoms:
                fhir_patient["telecom"] = telecoms

            if contact.get("address"):
                addr = contact["address"]
                if isinstance(addr, dict):
                    fhir_patient["address"] = [
                        {
                            "use": "home",
                            "line": [addr.get("street", "")] if addr.get("street") else [],
                            "city": addr.get("city"),
                            "state": addr.get("state"),
                            "postalCode": addr.get("zip") or addr.get("postal_code"),
                        }
                    ]
                elif isinstance(addr, str) and addr.strip():
                    fhir_patient["address"] = [{"use": "home", "text": addr.strip()}]

        return fhir_patient

    @classmethod
    def to_fhir_document_reference(
        cls,
        record: Any,
        patient_id: str,
        encounter_id: Optional[str] = None,
        base_system_url: str = "http://hospital.smarthealth.org",
    ) -> Dict[str, Any]:
        """Map canonical clinical record intermediate representation into an HL7 FHIR R4 DocumentReference."""
        import base64

        is_obj = hasattr(record, "cleaned_text") or hasattr(record, "content_text")

        rec_id = getattr(record, "id", None) if is_obj else record.get("id")
        rec_id = str(rec_id) if rec_id else str(uuid.uuid4())

        content_text = ""
        if is_obj:
            content_text = getattr(record, "cleaned_text", None) or getattr(record, "content_text", None) or getattr(record, "original_content", None) or ""
        else:
            content_text = record.get("cleaned_text") or record.get("content_text") or record.get("original_content") or ""

        rec_type = (getattr(record, "record_type", None) if is_obj else record.get("record_type")) or (getattr(record, "doc_type", None) if is_obj else record.get("doc_type")) or "clinical_note"
        rec_type_lower = str(rec_type).lower().replace(" ", "_")

        loinc_map = {
            "outpatient_note": ("34108-1", "Outpatient Note"),
            "progress_note": ("11506-3", "Progress note"),
            "discharge_summary": ("18842-5", "Discharge summary"),
            "consultation_note": ("11488-4", "Consultation note"),
            "procedure_note": ("28570-0", "Procedure note"),
            "history_and_physical": ("34117-2", "History and physical note"),
            "clinical_note": ("34108-1", "Outpatient Note"),
        }
        loinc_code, loinc_display = loinc_map.get(rec_type_lower, ("34108-1", "Outpatient Note"))

        rec_date = getattr(record, "record_date", None) if is_obj else record.get("record_date")
        if not rec_date:
            rec_date = getattr(record, "date", None) if is_obj else record.get("date")

        iso_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if rec_date:
            r_str = str(rec_date).strip()
            if "T" in r_str:
                iso_date = r_str if r_str.endswith("Z") or "+" in r_str else f"{r_str}Z"
            else:
                iso_date = f"{r_str}T00:00:00Z"

        b64_data = base64.b64encode(content_text.encode("utf-8")).decode("ascii")

        doc_ref: Dict[str, Any] = {
            "resourceType": "DocumentReference",
            "id": rec_id,
            "status": "current",
            "docStatus": "final",
            "type": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": loinc_display,
                    }
                ],
                "text": loinc_display,
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                            "code": "clinical-note",
                            "display": "Clinical Note",
                        }
                    ],
                    "text": "Clinical Note",
                }
            ],
            "subject": {"reference": f"Patient/{patient_id}"},
            "date": iso_date,
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain; charset=utf-8",
                        "data": b64_data,
                        "title": f"{loinc_display} - {rec_id}",
                    }
                }
            ],
        }

        effective_enc = encounter_id or (getattr(record, "encounter_id", None) if is_obj else record.get("encounter_id"))
        if effective_enc:
            doc_ref["context"] = {"encounter": [{"reference": f"Encounter/{effective_enc}"}]}

        return doc_ref

    @classmethod
    def to_fhir_diagnostic_report(
        cls,
        report: Any,
        patient_id: str,
        encounter_id: Optional[str] = None,
        observation_ids: Optional[List[str]] = None,
        base_system_url: str = "http://hospital.smarthealth.org",
    ) -> Dict[str, Any]:
        """Map canonical diagnostic report into an HL7 FHIR R4 DiagnosticReport resource."""
        is_obj = hasattr(report, "status") or hasattr(report, "code")

        dr_id = getattr(report, "id", None) if is_obj else report.get("id")
        dr_id = str(dr_id) if dr_id else str(uuid.uuid4())

        status_raw = (getattr(report, "status", None) if is_obj else report.get("status")) or "final"
        valid_statuses = {
            "registered", "partial", "preliminary", "final", "amended",
            "corrected", "appended", "cancelled", "entered-in-error", "unknown"
        }
        report_status = status_raw.lower() if status_raw.lower() in valid_statuses else "final"

        cat_code = (getattr(report, "category", None) if is_obj else report.get("category")) or "LAB"
        code_val = (getattr(report, "code", None) if is_obj else report.get("code")) or "24323-8"
        display_val = (getattr(report, "display", None) if is_obj else report.get("display")) or "Diagnostic Report"

        eff_date = getattr(report, "effective_date", None) if is_obj else report.get("effective_date")
        iso_effective = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if eff_date:
            e_str = str(eff_date).strip()
            iso_effective = e_str if ("T" in e_str and (e_str.endswith("Z") or "+" in e_str)) else (f"{e_str}Z" if "T" in e_str else f"{e_str}T00:00:00Z")

        conclusion = getattr(report, "conclusion", None) if is_obj else report.get("conclusion")

        diag_report: Dict[str, Any] = {
            "resourceType": "DiagnosticReport",
            "id": dr_id,
            "status": report_status,
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                            "code": cat_code,
                            "display": "Laboratory" if cat_code == "LAB" else cat_code,
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": code_val,
                        "display": display_val,
                    }
                ],
                "text": display_val,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": iso_effective,
            "issued": iso_effective,
        }

        effective_enc = encounter_id or (getattr(report, "encounter_id", None) if is_obj else report.get("encounter_id"))
        if effective_enc:
            diag_report["encounter"] = {"reference": f"Encounter/{effective_enc}"}

        obs_refs = []
        for oid in (observation_ids or []):
            obs_refs.append({"reference": f"Observation/{oid}"})
        if obs_refs:
            diag_report["result"] = obs_refs

        if conclusion:
            diag_report["conclusion"] = str(conclusion)

        return diag_report

    @classmethod
    def to_fhir_encounter(
        cls,
        encounter: Any,
        patient_id: str,
        base_system_url: str = "http://hospital.smarthealth.org",
    ) -> Dict[str, Any]:
        """Map canonical encounter into an HL7 FHIR R4 Encounter resource."""
        is_obj = hasattr(encounter, "encounter_class") or hasattr(encounter, "status")

        enc_id = getattr(encounter, "id", None) if is_obj else encounter.get("id")
        enc_id = str(enc_id) if enc_id else str(uuid.uuid4())

        status_raw = (getattr(encounter, "status", None) if is_obj else encounter.get("status")) or "finished"
        valid_statuses = {"planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled"}
        enc_status = status_raw.lower() if status_raw.lower() in valid_statuses else "finished"

        enc_class = (getattr(encounter, "encounter_class", None) if is_obj else encounter.get("encounter_class")) or "AMB"
        enc_class_upper = str(enc_class).upper()
        if enc_class_upper not in ["AMB", "IMP", "EMER", "VR", "HH"]:
            enc_class_upper = "AMB"

        start_date = getattr(encounter, "start_date", None) if is_obj else encounter.get("start_date")
        end_date = getattr(encounter, "end_date", None) if is_obj else encounter.get("end_date")

        fhir_encounter: Dict[str, Any] = {
            "resourceType": "Encounter",
            "id": enc_id,
            "status": enc_status,
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": enc_class_upper,
                "display": "ambulatory" if enc_class_upper == "AMB" else enc_class_upper.lower(),
            },
            "subject": {"reference": f"Patient/{patient_id}"},
        }

        if start_date:
            s_str = str(start_date).strip()
            iso_start = s_str if ("T" in s_str and (s_str.endswith("Z") or "+" in s_str)) else (f"{s_str}Z" if "T" in s_str else f"{s_str}T00:00:00Z")
            period: Dict[str, Any] = {"start": iso_start}
            if end_date:
                e_str = str(end_date).strip()
                iso_end = e_str if ("T" in e_str and (e_str.endswith("Z") or "+" in e_str)) else (f"{e_str}Z" if "T" in e_str else f"{e_str}T00:00:00Z")
                period["end"] = iso_end
            fhir_encounter["period"] = period

        reason = getattr(encounter, "reason_display", None) if is_obj else encounter.get("reason_display")
        reason_code = getattr(encounter, "reason_code", None) if is_obj else encounter.get("reason_code")
        if reason or reason_code:
            fhir_encounter["reasonCode"] = [
                {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": reason_code or "UNK",
                            "display": reason or "Clinical Encounter Reason",
                        }
                    ],
                    "text": reason or reason_code,
                }
            ]

        return fhir_encounter

    @classmethod
    def to_fhir_observation(
        cls,
        obs: Any,
        patient_id: str,
        encounter_id: Optional[str] = None,
        base_system_url: str = "http://hospital.smarthealth.org",
    ) -> Dict[str, Any]:
        """Map canonical observation into an HL7 FHIR R4 Observation resource."""
        is_obj = hasattr(obs, "code") or hasattr(obs, "status")

        obs_id = getattr(obs, "id", None) if is_obj else obs.get("id")
        obs_id = str(obs_id) if obs_id else str(uuid.uuid4())

        status_raw = (getattr(obs, "status", None) if is_obj else obs.get("status")) or "final"
        code_val = (getattr(obs, "code", None) if is_obj else obs.get("code")) or "8867-4"
        display_val = (getattr(obs, "display", None) if is_obj else obs.get("display")) or "Clinical Observation"
        code_sys = (getattr(obs, "code_system", None) if is_obj else obs.get("code_system")) or "http://loinc.org"
        category = (getattr(obs, "category", None) if is_obj else obs.get("category")) or "vital-signs"

        val_numeric = getattr(obs, "value_numeric", None) if is_obj else obs.get("value_numeric")
        val_text = (getattr(obs, "value_string", None) or getattr(obs, "value_text", None)) if is_obj else (obs.get("value_string") or obs.get("value_text"))
        raw_unit = (getattr(obs, "unit", None) or getattr(obs, "value_unit", None)) if is_obj else (obs.get("unit") or obs.get("value_unit"))
        unit = str(raw_unit).strip() if raw_unit else ""

        eff_date = getattr(obs, "effective_date", None) if is_obj else obs.get("effective_date")
        iso_effective = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if eff_date:
            e_str = str(eff_date).strip()
            iso_effective = e_str if ("T" in e_str and (e_str.endswith("Z") or "+" in e_str)) else (f"{e_str}Z" if "T" in e_str else f"{e_str}T00:00:00Z")

        fhir_obs: Dict[str, Any] = {
            "resourceType": "Observation",
            "id": obs_id,
            "status": status_raw.lower() if status_raw.lower() in ["registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"] else "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": category,
                            "display": category,
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": code_sys,
                        "code": code_val,
                        "display": display_val,
                    }
                ],
                "text": display_val,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": iso_effective,
        }

        effective_enc = encounter_id or (getattr(obs, "encounter_id", None) if is_obj else obs.get("encounter_id"))
        if effective_enc:
            fhir_obs["encounter"] = {"reference": f"Encounter/{effective_enc}"}

        if val_numeric is not None:
            vq: Dict[str, Any] = {"value": float(val_numeric)}
            if unit:
                vq["unit"] = unit
                vq["system"] = "http://unitsofmeasure.org"
                vq["code"] = unit
            fhir_obs["valueQuantity"] = vq
        elif val_text:
            fhir_obs["valueString"] = str(val_text)

        return fhir_obs
