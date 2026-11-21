"""HL7 FHIR R4 Bundle Builder and Reference Graph Engine.

Coordinates patient-centric Bundle assembly, resource reference integrity,
cross-patient isolation, and transaction/collection bundle formatting.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from app.core.exceptions import ValidationException
from app.core.logging import get_logger
from app.fhir.mapper import extract_reference_id

logger = get_logger(__name__)


class FHIRBundleBuilder:
    """Constructs compliant HL7 FHIR R4 Bundles with strict referential integrity."""

    def __init__(
        self,
        patient_id: str,
        bundle_id: Optional[str] = None,
        bundle_type: str = "collection",
        base_url: str = "http://hospital.smarthealth.org/fhir",
    ) -> None:
        self.patient_id = patient_id
        self.bundle_id = bundle_id or f"bundle-{patient_id}-{uuid.uuid4().hex[:8]}"
        self.bundle_type = bundle_type.lower()
        self.base_url = base_url.rstrip("/")
        self.resources: List[Dict[str, Any]] = []
        self._resource_ids: Set[Tuple[str, str]] = set()  # (resourceType, id)

    def add_resource(self, resource: Dict[str, Any]) -> None:
        """Add a FHIR resource dictionary to the bundle accumulator."""
        res_type = resource.get("resourceType")
        res_id = resource.get("id")

        if not res_type or not res_id:
            raise ValidationException("Resource must contain both 'resourceType' and 'id'")

        key = (res_type, str(res_id))
        if key in self._resource_ids:
            logger.debug("Resource %s/%s already present in bundle, skipping duplicate", res_type, res_id)
            return

        self.resources.append(resource)
        self._resource_ids.add(key)

    def add_resources(self, resources: List[Dict[str, Any]]) -> None:
        """Add multiple resources to the bundle."""
        for res in resources:
            if res:
                self.add_resource(res)

    def verify_patient_isolation(self) -> Tuple[bool, List[str]]:
        """Verify that every resource in the bundle belongs exclusively to this patient.

        Detects cross-patient references and dangling subject links.
        Returns:
            Tuple of (is_valid: bool, errors: List[str])
        """
        errors: List[str] = []
        expected_patient_ref = f"Patient/{self.patient_id}"

        for res in self.resources:
            res_type = res.get("resourceType")
            res_id = res.get("id")

            if res_type == "Patient":
                if str(res_id) != str(self.patient_id):
                    errors.append(
                        f"Cross-patient violation: Bundle for patient '{self.patient_id}' contains Patient resource with id '{res_id}'"
                    )
                continue

            subj = res.get("subject", {})
            subj_ref = subj.get("reference")
            if subj_ref:
                ref_id = extract_reference_id(subj_ref)
                if ref_id and str(ref_id) != str(self.patient_id):
                    errors.append(
                        f"Cross-patient reference in {res_type}/{res_id}: references 'Patient/{ref_id}', expected 'Patient/{self.patient_id}'"
                    )
            elif res_type in ["DocumentReference", "DiagnosticReport", "Observation", "Condition", "Encounter"]:
                errors.append(
                    f"Missing subject reference in {res_type}/{res_id}: required reference to Patient/{self.patient_id}"
                )

        return len(errors) == 0, errors

    def verify_internal_references(self) -> Tuple[bool, List[str]]:
        """Verify that internal references (e.g. Encounter, Observation) resolve within bundle or are valid.

        Returns:
            Tuple of (is_valid: bool, warnings_or_errors: List[str])
        """
        issues: List[str] = []
        encounter_ids = {rid for rtype, rid in self._resource_ids if rtype == "Encounter"}
        observation_ids = {rid for rtype, rid in self._resource_ids if rtype == "Observation"}

        for res in self.resources:
            res_type = res.get("resourceType")
            res_id = res.get("id")

            enc_ref_str = None
            if "encounter" in res and isinstance(res["encounter"], dict):
                enc_ref_str = res["encounter"].get("reference")
            elif "context" in res and isinstance(res["context"], dict) and "encounter" in res["context"]:
                enc_list = res["context"]["encounter"]
                if enc_list and isinstance(enc_list[0], dict):
                    enc_ref_str = enc_list[0].get("reference")

            if enc_ref_str:
                enc_id = extract_reference_id(enc_ref_str)
                if enc_id and encounter_ids and enc_id not in encounter_ids:
                    issues.append(
                        f"Dangling reference in {res_type}/{res_id}: referenced Encounter/{enc_id} not present in bundle"
                    )

            if res_type == "DiagnosticReport" and "result" in res:
                for res_entry in res.get("result", []):
                    ref_str = res_entry.get("reference")
                    obs_id = extract_reference_id(ref_str)
                    if obs_id and observation_ids and obs_id not in observation_ids:
                        issues.append(
                            f"Dangling result reference in DiagnosticReport/{res_id}: referenced Observation/{obs_id} not in bundle"
                        )

        return len(issues) == 0, issues

    def build(self) -> Dict[str, Any]:
        """Construct the complete HL7 FHIR R4 Bundle dictionary.

        Returns:
            Dict conforming to the FHIR R4 Bundle resource specification.
        """
        is_isolated, isolation_errors = self.verify_patient_isolation()
        if not is_isolated:
            raise ValidationException(
                f"Cannot build bundle due to cross-patient reference violations: {'; '.join(isolation_errors)}"
            )

        entries: List[Dict[str, Any]] = []

        sorted_resources = sorted(
            self.resources,
            key=lambda r: 0 if r.get("resourceType") == "Patient" else 1,
        )

        for res in sorted_resources:
            res_type = res.get("resourceType")
            res_id = res.get("id")
            full_url = f"{self.base_url}/{res_type}/{res_id}"

            entry: Dict[str, Any] = {
                "fullUrl": full_url,
                "resource": res,
            }

            if self.bundle_type == "transaction":
                entry["request"] = {
                    "method": "PUT",
                    "url": f"{res_type}/{res_id}",
                }

            entries.append(entry)

        bundle: Dict[str, Any] = {
            "resourceType": "Bundle",
            "id": self.bundle_id,
            "type": self.bundle_type,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total": len(entries),
            "entry": entries,
        }

        return bundle
