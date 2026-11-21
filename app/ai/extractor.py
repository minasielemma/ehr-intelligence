"""FHIR R4 Clinical Data Extraction & Referential Resolution Engine.

Extracts patient demographics, encounter timelines, active/historical diagnoses,
categorized observations, laboratory/imaging diagnostic reports, clinical notes,
and explicit clinical anomalies without relying on bundle resource ordering.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.logging import get_logger
from app.fhir.mapper import extract_reference_id

logger = get_logger(__name__)

# Common clinical interpretation codes signifying explicit abnormalities
ABNORMAL_INTERPRETATION_CODES = {
    "H", "HH", "HIGH", "L", "LL", "LOW", "A", "AA", "ABNORMAL",
    "CRIT", "CRITICAL", "POS", "POSITIVE", "DET", "DETECTED",
}


@dataclass
class ExtractedPatient:
    """Normalized patient demographics."""
    id: str
    mrn: str
    age_years: Optional[int] = None
    date_of_birth: Optional[str] = None
    gender: str = "unknown"
    source_reference: str = ""


@dataclass
class ExtractedEncounter:
    """Clinical encounter details."""
    id: str
    encounter_type: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    reason: Optional[str] = None
    status: str = "finished"
    source_reference: str = ""


@dataclass
class ExtractedCondition:
    """Clinical diagnosis or condition."""
    id: str
    name: str
    clinical_status: str  # active, resolved, recurrence, remission
    verification_status: str  # confirmed, provisional, differential, refuted
    onset_date: Optional[str] = None
    category: str = "problem-list-item"
    source_reference: str = ""


@dataclass
class ExtractedObservation:
    """Diagnostic observation or laboratory measurement."""
    id: str
    name: str
    category: str  # laboratory, vital-signs, imaging, exam, other
    value: Optional[str] = None
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    reference_range_low: Optional[float] = None
    reference_range_high: Optional[float] = None
    reference_range_text: Optional[str] = None
    interpretation: Optional[str] = None
    is_abnormal: bool = False
    effective_date: Optional[str] = None
    status: str = "final"
    source_reference: str = ""


@dataclass
class ExtractedDiagnosticReport:
    """Laboratory or radiological diagnostic report."""
    id: str
    name: str
    category: str  # LAB, RAD, other
    status: str = "final"
    effective_date: Optional[str] = None
    conclusion: Optional[str] = None
    observation_ids: List[str] = field(default_factory=list)
    source_reference: str = ""


@dataclass
class ExtractedClinicalNote:
    """Free-text clinical note or document reference."""
    id: str
    title: str
    date: Optional[str] = None
    content_text: str = ""
    source_reference: str = ""


@dataclass
class ExtractedMedication:
    """Prescribed or administered medication."""
    id: str
    name: str
    status: str
    dosage: Optional[str] = None
    source_reference: str = ""


@dataclass
class ExtractedClinicalRecord:
    """Consolidated extracted clinical data model ready for prompt formatting and evaluation."""
    patient: ExtractedPatient
    encounters: List[ExtractedEncounter] = field(default_factory=list)
    conditions: List[ExtractedCondition] = field(default_factory=list)
    observations: List[ExtractedObservation] = field(default_factory=list)
    diagnostic_reports: List[ExtractedDiagnosticReport] = field(default_factory=list)
    clinical_notes: List[ExtractedClinicalNote] = field(default_factory=list)
    medications: List[ExtractedMedication] = field(default_factory=list)
    flagged_anomalies: List[str] = field(default_factory=list)
    source_references: List[str] = field(default_factory=list)
    chief_concern: Optional[str] = None
    redact_phi: bool = True


class FHIRClinicalExtractor:
    """Extracts structured clinical facts, references, and anomalies from FHIR R4 Bundles."""

    def __init__(self, redact_phi: bool = True) -> None:
        self.redact_phi = redact_phi

    def extract_from_bundle(self, bundle: Dict[str, Any]) -> ExtractedClinicalRecord:
        """Parse an HL7 FHIR R4 Bundle into an ExtractedClinicalRecord.

        Handles arbitrary resource ordering and safely resolves cross-resource references.
        """
        resources: List[Dict[str, Any]] = []
        if bundle.get("resourceType") == "Bundle":
            for entry in bundle.get("entry", []):
                res = entry.get("resource")
                if res and isinstance(res, dict):
                    resources.append(res)
        elif isinstance(bundle, dict) and "resourceType" in bundle:
            resources.append(bundle)

        return self.extract_from_resources(resources)

    def extract_from_resources(self, resources: List[Dict[str, Any]]) -> ExtractedClinicalRecord:
        """Extract clinical facts from a list of FHIR resources."""
        # 1. Build fast resolution index by (resourceType, id) and resourceType/id
        resource_index: Dict[str, Dict[str, Any]] = {}
        by_type: Dict[str, List[Dict[str, Any]]] = {}

        for res in resources:
            r_type = res.get("resourceType")
            r_id = str(res.get("id", ""))
            if r_type and r_id:
                key = f"{r_type}/{r_id}"
                resource_index[key] = res
                resource_index[r_id] = res
                by_type.setdefault(r_type, []).append(res)

        # 2. Extract Patient demographics
        patient_res = by_type.get("Patient", [{}])[0]
        patient = self._extract_patient(patient_res)

        # 3. Extract Encounters
        encounters = [self._extract_encounter(r) for r in by_type.get("Encounter", [])]

        # 4. Extract Conditions
        conditions = [self._extract_condition(r) for r in by_type.get("Condition", [])]

        # 5. Extract Observations
        observations = [self._extract_observation(r) for r in by_type.get("Observation", [])]
        obs_map = {o.id: o for o in observations}

        # 6. Extract DiagnosticReports (resolving linked observations)
        diagnostic_reports = [
            self._extract_diagnostic_report(r, obs_map)
            for r in by_type.get("DiagnosticReport", [])
        ]

        # 7. Extract Clinical Notes (DocumentReference)
        clinical_notes = [
            self._extract_clinical_note(r)
            for r in by_type.get("DocumentReference", [])
        ]

        # 8. Extract Medications
        medications = [
            self._extract_medication(r)
            for r in by_type.get("MedicationRequest", []) + by_type.get("MedicationAdministration", [])
        ]

        # 9. Derive Chief Concern
        chief_concern = self._derive_chief_concern(encounters, conditions, clinical_notes)

        # 10. Identify Explicit Anomalies & Discrepancies
        anomalies = self._identify_anomalies(
            observations=observations,
            diagnostic_reports=diagnostic_reports,
            conditions=conditions,
            clinical_notes=clinical_notes,
        )

        # 11. Compile all source references
        all_refs: Set[str] = set()
        if patient.source_reference:
            all_refs.add(patient.source_reference)
        for enc in encounters:
            all_refs.add(enc.source_reference)
        for cond in conditions:
            all_refs.add(cond.source_reference)
        for obs in observations:
            all_refs.add(obs.source_reference)
        for dr in diagnostic_reports:
            all_refs.add(dr.source_reference)
        for cn in clinical_notes:
            all_refs.add(cn.source_reference)
        for med in medications:
            all_refs.add(med.source_reference)

        sorted_refs = sorted(list(all_refs))

        return ExtractedClinicalRecord(
            patient=patient,
            encounters=encounters,
            conditions=conditions,
            observations=observations,
            diagnostic_reports=diagnostic_reports,
            clinical_notes=clinical_notes,
            medications=medications,
            flagged_anomalies=anomalies,
            source_references=sorted_refs,
            chief_concern=chief_concern,
            redact_phi=self.redact_phi,
        )

    def _extract_patient(self, res: Dict[str, Any]) -> ExtractedPatient:
        """Extract Patient demographics with age calculation and optional pseudonymization."""
        p_id = str(res.get("id", "UNKNOWN"))
        mrn = "UNKNOWN"
        for ident in res.get("identifier", []):
            val = ident.get("value")
            if val:
                mrn = str(val)
                break

        dob_str = res.get("birthDate")
        age_years: Optional[int] = None
        if dob_str:
            try:
                # Handle YYYY-MM-DD or full ISO
                birth_dt = datetime.fromisoformat(dob_str.split("T")[0])
                today = datetime.now(timezone.utc).date()
                age_years = today.year - birth_dt.year - ((today.month, today.day) < (birth_dt.month, birth_dt.day))
            except Exception:
                pass

        gender = str(res.get("gender", "unknown")).lower()
        source_ref = f"Patient/{p_id}" if p_id != "UNKNOWN" else ""

        return ExtractedPatient(
            id=p_id,
            mrn=mrn,
            age_years=age_years,
            date_of_birth=dob_str,
            gender=gender,
            source_reference=source_ref,
        )

    def _extract_encounter(self, res: Dict[str, Any]) -> ExtractedEncounter:
        """Extract encounter details."""
        e_id = str(res.get("id", "UNKNOWN"))
        enc_class = res.get("class", {})
        enc_class_code = enc_class.get("code") or enc_class.get("display") or "AMB"

        types = res.get("type", [])
        type_str = ""
        if types and isinstance(types[0], dict):
            type_str = types[0].get("text") or (types[0].get("coding", [{}])[0].get("display", ""))
        
        name = type_str or enc_class_code

        period = res.get("period", {})
        start_date = period.get("start")
        end_date = period.get("end")

        reason_list = res.get("reasonCode", [])
        reason_str = None
        if reason_list and isinstance(reason_list[0], dict):
            reason_str = reason_list[0].get("text") or (reason_list[0].get("coding", [{}])[0].get("display"))

        status = res.get("status", "finished")

        return ExtractedEncounter(
            id=e_id,
            encounter_type=name,
            start_date=start_date,
            end_date=end_date,
            reason=reason_str,
            status=status,
            source_reference=f"Encounter/{e_id}",
        )

    def _extract_condition(self, res: Dict[str, Any]) -> ExtractedCondition:
        """Extract clinical condition and verification status."""
        c_id = str(res.get("id", "UNKNOWN"))
        code_obj = res.get("code", {})
        name = code_obj.get("text")
        if not name and code_obj.get("coding"):
            name = code_obj["coding"][0].get("display") or code_obj["coding"][0].get("code")
        if not name:
            name = "Unspecified Condition"

        clin_status = "active"
        if "clinicalStatus" in res and res["clinicalStatus"].get("coding"):
            clin_status = res["clinicalStatus"]["coding"][0].get("code", "active")

        ver_status = "confirmed"
        if "verificationStatus" in res and res["verificationStatus"].get("coding"):
            ver_status = res["verificationStatus"]["coding"][0].get("code", "confirmed")

        onset = res.get("onsetDateTime") or res.get("recordedDate")
        
        cat = "problem-list-item"
        if res.get("category") and res["category"][0].get("coding"):
            cat = res["category"][0]["coding"][0].get("code", "problem-list-item")

        return ExtractedCondition(
            id=c_id,
            name=name,
            clinical_status=clin_status,
            verification_status=ver_status,
            onset_date=onset,
            category=cat,
            source_reference=f"Condition/{c_id}",
        )

    def _extract_observation(self, res: Dict[str, Any]) -> ExtractedObservation:
        """Extract clinical observation, lab value, reference ranges, and abnormal flags."""
        o_id = str(res.get("id", "UNKNOWN"))
        code_obj = res.get("code", {})
        name = code_obj.get("text")
        if not name and code_obj.get("coding"):
            name = code_obj["coding"][0].get("display") or code_obj["coding"][0].get("code")
        if not name:
            name = "Unspecified Observation"

        # Determine category
        cat = "other"
        cats = res.get("category", [])
        if cats and isinstance(cats[0], dict) and cats[0].get("coding"):
            cat = str(cats[0]["coding"][0].get("code", "other")).lower()

        # Extract value
        val_str: Optional[str] = None
        num_val: Optional[float] = None
        unit: Optional[str] = None

        if "valueQuantity" in res:
            vq = res["valueQuantity"]
            num_val = vq.get("value")
            unit = vq.get("unit") or vq.get("code")
            val_str = f"{num_val} {unit}".strip() if unit else str(num_val)
        elif "valueString" in res:
            val_str = res["valueString"]
        elif "valueCodeableConcept" in res:
            vc = res["valueCodeableConcept"]
            val_str = vc.get("text") or (vc.get("coding", [{}])[0].get("display"))

        # Extract reference range
        rr_low: Optional[float] = None
        rr_high: Optional[float] = None
        rr_text: Optional[str] = None

        if "referenceRange" in res and res["referenceRange"]:
            rr = res["referenceRange"][0]
            if "low" in rr and rr["low"].get("value") is not None:
                rr_low = float(rr["low"]["value"])
            if "high" in rr and rr["high"].get("value") is not None:
                rr_high = float(rr["high"]["value"])
            rr_text = rr.get("text")
            if not rr_text and (rr_low is not None or rr_high is not None):
                rr_text = f"{rr_low if rr_low is not None else ''} - {rr_high if rr_high is not None else ''} {unit or ''}".strip()

        # Extract interpretation
        interp: Optional[str] = None
        interps = res.get("interpretation", [])
        if interps and isinstance(interps[0], dict):
            interp = interps[0].get("text")
            if not interp and interps[0].get("coding"):
                interp = interps[0]["coding"][0].get("code")

        # Determine abnormality
        is_abnormal = False
        if interp and interp.upper() in ABNORMAL_INTERPRETATION_CODES:
            is_abnormal = True
        elif num_val is not None:
            if rr_low is not None and num_val < rr_low:
                is_abnormal = True
            elif rr_high is not None and num_val > rr_high:
                is_abnormal = True

        effective = res.get("effectiveDateTime")
        status = res.get("status", "final")

        return ExtractedObservation(
            id=o_id,
            name=name,
            category=cat,
            value=val_str,
            numeric_value=num_val,
            unit=unit,
            reference_range_low=rr_low,
            reference_range_high=rr_high,
            reference_range_text=rr_text,
            interpretation=interp,
            is_abnormal=is_abnormal,
            effective_date=effective,
            status=status,
            source_reference=f"Observation/{o_id}",
        )

    def _extract_diagnostic_report(
        self, res: Dict[str, Any], obs_map: Dict[str, ExtractedObservation]
    ) -> ExtractedDiagnosticReport:
        """Extract diagnostic report and link referenced observation identifiers."""
        dr_id = str(res.get("id", "UNKNOWN"))
        code_obj = res.get("code", {})
        name = code_obj.get("text")
        if not name and code_obj.get("coding"):
            name = code_obj["coding"][0].get("display") or code_obj["coding"][0].get("code")
        if not name:
            name = "Diagnostic Report"

        cat = "other"
        cats = res.get("category", [])
        if cats and isinstance(cats[0], dict) and cats[0].get("coding"):
            cat_code = cats[0]["coding"][0].get("code", "other").upper()
            if "LAB" in cat_code:
                cat = "laboratory"
            elif "RAD" in cat_code:
                cat = "imaging"
            else:
                cat = cat_code.lower()

        status = res.get("status", "final")
        effective = res.get("effectiveDateTime") or res.get("issued")
        conclusion = res.get("conclusion")

        linked_obs_ids: List[str] = []
        for r_entry in res.get("result", []):
            ref = r_entry.get("reference")
            obs_id = extract_reference_id(ref)
            if obs_id:
                linked_obs_ids.append(obs_id)

        return ExtractedDiagnosticReport(
            id=dr_id,
            name=name,
            category=cat,
            status=status,
            effective_date=effective,
            conclusion=conclusion,
            observation_ids=linked_obs_ids,
            source_reference=f"DiagnosticReport/{dr_id}",
        )

    def _extract_clinical_note(self, res: Dict[str, Any]) -> ExtractedClinicalNote:
        """Extract DocumentReference clinical note content, decoding base64 if present."""
        d_id = str(res.get("id", "UNKNOWN"))
        title = res.get("description")
        type_obj = res.get("type", {})
        if not title and type_obj.get("text"):
            title = type_obj["text"]
        elif not title and type_obj.get("coding"):
            title = type_obj["coding"][0].get("display")
        if not title:
            title = "Clinical Note"

        date_str = res.get("date")

        content_text = ""
        contents = res.get("content", [])
        if contents and isinstance(contents[0], dict):
            attach = contents[0].get("attachment", {})
            b64_data = attach.get("data")
            if b64_data:
                try:
                    content_text = base64.b64decode(b64_data).decode("utf-8", errors="replace")
                except Exception:
                    content_text = b64_data
            elif attach.get("url"):
                content_text = f"[Attached Document at {attach['url']}]"

        return ExtractedClinicalNote(
            id=d_id,
            title=title,
            date=date_str,
            content_text=content_text,
            source_reference=f"DocumentReference/{d_id}",
        )

    def _extract_medication(self, res: Dict[str, Any]) -> ExtractedMedication:
        """Extract medication orders or administration records."""
        m_id = str(res.get("id", "UNKNOWN"))
        r_type = res.get("resourceType", "MedicationRequest")
        
        med_obj = res.get("medicationCodeableConcept", {})
        name = med_obj.get("text")
        if not name and med_obj.get("coding"):
            name = med_obj["coding"][0].get("display") or med_obj["coding"][0].get("code")
        if not name:
            med_ref = res.get("medicationReference", {})
            name = med_ref.get("display") or extract_reference_id(med_ref.get("reference")) or "Medication"

        status = res.get("status", "unknown")
        
        dosage_str: Optional[str] = None
        dosages = res.get("dosageInstruction", [])
        if dosages and isinstance(dosages[0], dict):
            dosage_str = dosages[0].get("text")

        return ExtractedMedication(
            id=m_id,
            name=name,
            status=status,
            dosage=dosage_str,
            source_reference=f"{r_type}/{m_id}",
        )

    def _derive_chief_concern(
        self,
        encounters: List[ExtractedEncounter],
        conditions: List[ExtractedCondition],
        notes: List[ExtractedClinicalNote],
    ) -> Optional[str]:
        """Derive the presenting chief concern from encounters, notes, or active conditions."""
        # 1. Prefer explicit encounter reason
        for enc in reversed(encounters):
            if enc.reason:
                return enc.reason

        # 2. Extract from clinical notes via common clinical header patterns
        for note in reversed(notes):
            if note.content_text:
                cc_match = re.search(
                    r"(?:CHIEF\s+COMPLAINT|REASON\s+FOR\s+VISIT|PRESENTING\s+CONCERN)[\s:]+([^\.\n]+)",
                    note.content_text,
                    re.IGNORECASE,
                )
                if cc_match:
                    return cc_match.group(1).strip()

        # 3. Fall back to primary active encounter diagnosis or condition
        for cond in conditions:
            if cond.clinical_status == "active" and cond.category in ["encounter-diagnosis", "problem-list-item"]:
                return f"Evaluation of {cond.name}"

        return None

    def _identify_anomalies(
        self,
        observations: List[ExtractedObservation],
        diagnostic_reports: List[ExtractedDiagnosticReport],
        conditions: List[ExtractedCondition],
        clinical_notes: List[ExtractedClinicalNote],
    ) -> List[str]:
        """Detect and format explicitly documented abnormalities and conflicting records."""
        anomalies: List[str] = []

        # 1. Abnormal and out-of-range observations
        for obs in observations:
            if obs.is_abnormal:
                flag_str = f"Abnormal {obs.name}: {obs.value or 'abnormal result'}"
                if obs.reference_range_text:
                    flag_str += f" (Reference Range: {obs.reference_range_text})"
                if obs.interpretation:
                    flag_str += f" [Flag: {obs.interpretation}]"
                anomalies.append(flag_str)

        # 2. Critical findings in Diagnostic Reports
        for dr in diagnostic_reports:
            if dr.conclusion and any(
                term in dr.conclusion.lower()
                for term in ["critical", "acute", "infarct", "hemorrhage", "malignan", "perforat", "fracture", "mass"]
            ):
                anomalies.append(f"Significant Diagnostic Finding in {dr.name}: {dr.conclusion.strip()}")

        # 3. Conflicting Conditions (e.g. condition both active and resolved, or conflicting diagnoses)
        condition_status_map: Dict[str, Set[str]] = {}
        for c in conditions:
            condition_status_map.setdefault(c.name.lower(), set()).add(c.clinical_status)
        
        for name_key, statuses in condition_status_map.items():
            if "active" in statuses and "resolved" in statuses:
                anomalies.append(
                    f"Conflicting Records: '{name_key.title()}' is documented as both active and resolved across source records"
                )

        # 4. Check for unlinked critical diagnostic reports
        for dr in diagnostic_reports:
            if dr.category == "laboratory" and not dr.observation_ids and not dr.conclusion:
                anomalies.append(
                    f"Incomplete Record: DiagnosticReport '{dr.name}' (id: {dr.id}) contains neither linked observations nor conclusion"
                )

        return anomalies
