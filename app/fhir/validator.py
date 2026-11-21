"""Comprehensive HL7 FHIR R4 resource and Bundle validator.

Leverages official fhir.resources models with deep schema validation,
structural rules, reference integrity, cross-patient isolation checks,
and structured validation reporting.
"""

from datetime import datetime, timezone
import importlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.logging import get_logger
from app.fhir.mapper import extract_reference_id
from app.schemas.fhir import (
    FHIRValidationIssue,
    FHIRValidationReport,
    ValidationSeverity,
    ValidationStatus,
)

logger = get_logger(__name__)

# Standard FHIR R4 module map for dynamic resolution
FHIR_RESOURCE_MODULE_MAP = {
    "Patient": "patient",
    "Encounter": "encounter",
    "Condition": "condition",
    "Observation": "observation",
    "MedicationRequest": "medicationrequest",
    "MedicationAdministration": "medicationadministration",
    "Procedure": "procedure",
    "AllergyIntolerance": "allergyintolerance",
    "Immunization": "immunization",
    "Organization": "organization",
    "Practitioner": "practitioner",
    "Coverage": "coverage",
    "Claim": "claim",
    "CarePlan": "careplan",
    "Consent": "consent",
    "ServiceRequest": "servicerequest",
    "DiagnosticReport": "diagnosticreport",
    "ImagingStudy": "imagingstudy",
    "DocumentReference": "documentreference",
    "Provenance": "provenance",
    "AuditEvent": "auditevent",
    "Bundle": "bundle",
}


def get_fhir_model_class(res_type: str) -> Optional[Any]:
    """Retrieve the official fhir.resources Pydantic model class for a resourceType.

    Tries fhir.resources.R4B first for canonical R4 schema fidelity,
    then falls back to root fhir.resources.
    """
    mod_name = FHIR_RESOURCE_MODULE_MAP.get(res_type, res_type.lower())

    try:
        mod = importlib.import_module(f"fhir.resources.R4B.{mod_name}")
        if hasattr(mod, res_type):
            return getattr(mod, res_type)
    except Exception:
        pass

    try:
        mod = importlib.import_module(f"fhir.resources.{mod_name}")
        if hasattr(mod, res_type):
            return getattr(mod, res_type)
    except Exception:
        pass

    return None


class FHIRValidator:
    """Validates healthcare data payloads against the official HL7 FHIR R4 specification."""


    @classmethod
    def validate_resource(cls, resource_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate a FHIR resource dict against its official FHIR R4 model.

        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        if not isinstance(resource_data, dict):
            return False, "FHIR resource must be a JSON object"

        res_type = resource_data.get("resourceType")
        if not res_type:
            return False, "Missing required 'resourceType' field"

        model_cls = get_fhir_model_class(res_type)
        if not model_cls:
            return False, f"Unsupported or unrecognized FHIR R4 resourceType: '{res_type}'"

        prep_data = cls._prepare_resource_for_model(res_type, resource_data)

        try:
            if hasattr(model_cls, "model_validate"):
                model_cls.model_validate(prep_data)
            else:
                model_cls.parse_obj(prep_data)
            return True, None
        except Exception as exc:
            return False, f"FHIR R4 Conformance Error for {res_type}: {str(exc)}"

    @classmethod
    def validate_bundle(cls, bundle_data: Dict[str, Any]) -> Tuple[bool, int, List[str]]:
        """Validate an entire FHIR R4 Bundle and all containing resource entries.

        Returns:
            Tuple of (all_valid: bool, valid_count: int, list_of_errors: List[str])
        """
        is_bundle_valid, err = cls.validate_resource(bundle_data)
        if not is_bundle_valid:
            return False, 0, [err or "Invalid Bundle structure"]

        entries = bundle_data.get("entry", [])
        errors: List[str] = []
        valid_count = 0

        for idx, entry in enumerate(entries):
            res = entry.get("resource")
            if not res:
                errors.append(f"Bundle entry #{idx} is missing 'resource' object")
                continue
            ok, entry_err = cls.validate_resource(res)
            if ok:
                valid_count += 1
            else:
                errors.append(f"Entry #{idx} ({res.get('resourceType', 'Unknown')}): {entry_err}")

        return len(errors) == 0, valid_count, errors


    @classmethod
    def validate_resource_detailed(
        cls,
        resource_data: Dict[str, Any],
        fhir_path_prefix: str = "",
    ) -> List[FHIRValidationIssue]:
        """Perform granular schema, cardinality, primitive, and business rule validation.

        Returns:
            List of FHIRValidationIssue objects with actionable recommendations.
        """
        issues: List[FHIRValidationIssue] = []

        if not isinstance(resource_data, dict):
            issues.append(
                FHIRValidationIssue(
                    resource_type="Unknown",
                    severity=ValidationSeverity.ERROR,
                    fhir_path=fhir_path_prefix or "resource",
                    error_code="INVALID_DATA_TYPE",
                    description="FHIR resource must be a JSON object dictionary",
                    recommended_action="Ensure the payload is a valid JSON object",
                )
            )
            return issues

        res_type = resource_data.get("resourceType")
        res_id = resource_data.get("id")
        base_path = f"{fhir_path_prefix}{res_type}" if fhir_path_prefix else (res_type or "Resource")

        if not res_type:
            issues.append(
                FHIRValidationIssue(
                    resource_type="Unknown",
                    resource_id=res_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path=f"{base_path}.resourceType",
                    error_code="MISSING_REQUIRED_FIELD",
                    description="Resource is missing required 'resourceType' property",
                    recommended_action="Specify a recognized HL7 FHIR R4 resourceType",
                )
            )
            return issues

        model_cls = get_fhir_model_class(res_type)
        if not model_cls:
            issues.append(
                FHIRValidationIssue(
                    resource_type=res_type,
                    resource_id=res_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path=f"{base_path}.resourceType",
                    error_code="UNSUPPORTED_RESOURCE_TYPE",
                    description=f"Resource type '{res_type}' is not recognized in FHIR R4 specification",
                    recommended_action="Use a standard FHIR R4 resource type (e.g. Patient, DocumentReference, DiagnosticReport)",
                )
            )
            return issues

        if not res_id:
            issues.append(
                FHIRValidationIssue(
                    resource_type=res_type,
                    resource_id=None,
                    severity=ValidationSeverity.WARNING,
                    fhir_path=f"{base_path}.id",
                    error_code="MISSING_RESOURCE_ID",
                    description=f"Resource {res_type} does not have an 'id' attribute",
                    recommended_action="Assign a stable, unique resource ID",
                )
            )
        elif not re.match(r"^[A-Za-z0-9\-\.]{1,64}$", str(res_id)):
            issues.append(
                FHIRValidationIssue(
                    resource_type=res_type,
                    resource_id=res_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path=f"{base_path}.id",
                    error_code="INVALID_RESOURCE_ID_FORMAT",
                    description=f"Resource ID '{res_id}' contains invalid characters according to FHIR R4 ID regex [A-Za-z0-9\\-\\.]{{1,64}}",
                    recommended_action="Ensure resource ID is 1-64 characters containing only letters, numbers, hyphens, and dots",
                )
            )

        prep_data = cls._prepare_resource_for_model(res_type, resource_data)
        try:
            if hasattr(model_cls, "model_validate"):
                model_cls.model_validate(prep_data)
            else:
                model_cls.parse_obj(prep_data)
        except Exception as exc:
            cls._extract_pydantic_issues(exc, res_type, res_id, base_path, issues)

        cls._validate_clinical_semantics(res_type, resource_data, base_path, res_id, issues)

        return issues

    @classmethod
    def validate_bundle_detailed(
        cls,
        bundle_data: Dict[str, Any],
        expected_patient_id: Optional[str] = None,
    ) -> FHIRValidationReport:
        """Perform comprehensive conformance, reference graph, and cross-patient audit on a Bundle.

        Returns:
            Structured FHIRValidationReport detailing all issues and overall validation status.
        """
        all_issues: List[FHIRValidationIssue] = []
        patient_identifier = expected_patient_id or "UNKNOWN"
        bundle_id = bundle_data.get("id") if isinstance(bundle_data, dict) else None

        if not isinstance(bundle_data, dict):
            issue = FHIRValidationIssue(
                resource_type="Bundle",
                severity=ValidationSeverity.ERROR,
                fhir_path="Bundle",
                error_code="INVALID_DATA_TYPE",
                description="FHIR Bundle must be a JSON object dictionary",
                recommended_action="Provide a valid JSON dictionary representing the FHIR Bundle",
            )
            return FHIRValidationReport(
                patient_identifier=patient_identifier,
                bundle_id=bundle_id,
                status=ValidationStatus.INVALID,
                total_resources=0,
                valid_resources=0,
                invalid_resources=0,
                error_count=1,
                warning_count=0,
                info_count=0,
                issues=[issue],
            )

        bundle_copy = dict(bundle_data)
        bundle_copy_entryless = {k: v for k, v in bundle_copy.items() if k != "entry"}
        bundle_issues = cls.validate_resource_detailed(bundle_copy_entryless, fhir_path_prefix="")
        all_issues.extend(bundle_issues)

        b_type = bundle_data.get("type")
        if not b_type:
            all_issues.append(
                FHIRValidationIssue(
                    resource_type="Bundle",
                    resource_id=bundle_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path="Bundle.type",
                    error_code="MISSING_REQUIRED_FIELD",
                    description="Bundle is missing required 'type' element",
                    recommended_action="Set Bundle.type to 'collection', 'transaction', or 'document'",
                )
            )

        entries = bundle_data.get("entry", [])
        if not isinstance(entries, list):
            all_issues.append(
                FHIRValidationIssue(
                    resource_type="Bundle",
                    resource_id=bundle_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path="Bundle.entry",
                    error_code="INVALID_CARDINALITY",
                    description="Bundle 'entry' must be a JSON array",
                    recommended_action="Ensure 'entry' is an array of BundleEntry objects",
                )
            )
            entries = []

        total_resources = len(entries)
        valid_resources = 0
        invalid_resources = 0

        discovered_patient_id = expected_patient_id
        for entry in entries:
            res = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(res, dict) and res.get("resourceType") == "Patient":
                discovered_patient_id = res.get("id")
                patient_identifier = discovered_patient_id or patient_identifier
                break

        if not discovered_patient_id:
            for entry in entries:
                res = entry.get("resource") if isinstance(entry, dict) else None
                if isinstance(res, dict) and isinstance(res.get("subject"), dict):
                    ref_str = res["subject"].get("reference")
                    if ref_str:
                        extracted = extract_reference_id(ref_str)
                        if extracted:
                            discovered_patient_id = extracted
                            if patient_identifier == "UNKNOWN":
                                patient_identifier = extracted
                            break

        bundle_resource_index: Set[Tuple[str, str]] = set()
        for idx, entry in enumerate(entries):
            res = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(res, dict):
                r_type = res.get("resourceType")
                r_id = res.get("id")
                if r_type and r_id:
                    bundle_resource_index.add((r_type, str(r_id)))

        for idx, entry in enumerate(entries):
            entry_path = f"Bundle.entry[{idx}]"
            if not isinstance(entry, dict):
                all_issues.append(
                    FHIRValidationIssue(
                        resource_type="BundleEntry",
                        severity=ValidationSeverity.ERROR,
                        fhir_path=entry_path,
                        error_code="INVALID_ENTRY",
                        description=f"Bundle entry #{idx} is not an object",
                        recommended_action="Provide a valid BundleEntry dictionary",
                    )
                )
                invalid_resources += 1
                continue

            res = entry.get("resource")
            if not isinstance(res, dict):
                all_issues.append(
                    FHIRValidationIssue(
                        resource_type="BundleEntry",
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{entry_path}.resource",
                        error_code="MISSING_RESOURCE",
                        description=f"Bundle entry #{idx} is missing 'resource' object",
                        recommended_action="Include a valid FHIR resource within each Bundle entry",
                    )
                )
                invalid_resources += 1
                continue

            res_issues = cls.validate_resource_detailed(res, fhir_path_prefix=f"{entry_path}.")
            all_issues.extend(res_issues)

            cls._verify_entry_references(
                res=res,
                entry_path=entry_path,
                expected_patient_id=discovered_patient_id,
                bundle_index=bundle_resource_index,
                issues=all_issues,
            )

            has_entry_errors = any(
                iss.severity == ValidationSeverity.ERROR and iss.fhir_path.startswith(entry_path)
                for iss in all_issues
            )
            if has_entry_errors:
                invalid_resources += 1
            else:
                valid_resources += 1

        error_count = sum(1 for iss in all_issues if iss.severity == ValidationSeverity.ERROR)
        warning_count = sum(1 for iss in all_issues if iss.severity == ValidationSeverity.WARNING)
        info_count = sum(1 for iss in all_issues if iss.severity == ValidationSeverity.INFORMATION)

        if error_count > 0:
            status = ValidationStatus.INVALID
        elif warning_count > 0:
            status = ValidationStatus.WARNING
        else:
            status = ValidationStatus.VALID

        return FHIRValidationReport(
            patient_identifier=str(patient_identifier),
            bundle_id=bundle_id,
            status=status,
            total_resources=total_resources,
            valid_resources=valid_resources,
            invalid_resources=invalid_resources,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            issues=all_issues,
            validated_at=datetime.now(timezone.utc),
        )


    @classmethod
    def _normalize_encounter_class(cls, cls_v: Any) -> Any:
        enc_cls = get_fhir_model_class("Encounter")
        expects_coding = False
        if enc_cls and hasattr(enc_cls, "__fields__"):
            field = enc_cls.__fields__.get("class_fhir")
            if field and "Coding" in str(getattr(field, "type_", "")):
                expects_coding = True

        if expects_coding:
            if isinstance(cls_v, list):
                if not cls_v:
                    return {"code": "AMB", "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode"}
                first = cls_v[0]
                if isinstance(first, dict) and "coding" in first and isinstance(first["coding"], list) and first["coding"]:
                    return first["coding"][0]
                return first
            elif isinstance(cls_v, dict):
                if "coding" in cls_v and isinstance(cls_v["coding"], list) and cls_v["coding"]:
                    return cls_v["coding"][0]
                return cls_v
            return {"code": "AMB", "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode"}
        else:
            if isinstance(cls_v, dict):
                return [cls_v] if "coding" in cls_v else [{"coding": [cls_v]}]
            elif isinstance(cls_v, list):
                return cls_v
            return [{"coding": [{"code": "AMB", "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode"}]}]

    @classmethod
    def _prepare_resource_for_model(cls, res_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize edge-case field representations before passing to Pydantic models."""
        if res_type == "Encounter" and "class" in data:
            res_copy = dict(data)
            res_copy["class"] = cls._normalize_encounter_class(res_copy["class"])
            return res_copy
        elif res_type == "Bundle" and "entry" in data and isinstance(data["entry"], list):
            bundle_copy = dict(data)
            new_entries = []
            for ent in bundle_copy["entry"]:
                if isinstance(ent, dict) and isinstance(ent.get("resource"), dict):
                    sub_res = ent["resource"]
                    if sub_res.get("resourceType") == "Encounter" and "class" in sub_res:
                        sub_copy = dict(sub_res)
                        sub_copy["class"] = cls._normalize_encounter_class(sub_copy["class"])
                        new_entries.append({**ent, "resource": sub_copy})
                        continue
                new_entries.append(ent)
            bundle_copy["entry"] = new_entries
            return bundle_copy
        return data

    @classmethod
    def _extract_pydantic_issues(
        cls,
        exc: Exception,
        res_type: str,
        res_id: Optional[str],
        base_path: str,
        issues: List[FHIRValidationIssue],
    ) -> None:
        """Parse Pydantic validation errors into granular FHIRValidationIssue objects."""
        errors_list = []
        if hasattr(exc, "errors") and callable(exc.errors):
            try:
                errors_list = exc.errors()
            except Exception:
                errors_list = []

        if errors_list:
            for err in errors_list:
                loc = ".".join(str(p) for p in err.get("loc", []))
                loc_path = f"{base_path}.{loc}" if loc else base_path
                msg = err.get("msg", str(err))
                err_type = err.get("type", "VALIDATION_ERROR").upper().replace(".", "_")

                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=loc_path,
                        error_code=err_type,
                        description=f"FHIR R4 conformance violation: {msg}",
                        recommended_action=f"Correct the value or format at '{loc_path}' to satisfy FHIR R4 specification",
                    )
                )
        else:
            issues.append(
                FHIRValidationIssue(
                    resource_type=res_type,
                    resource_id=res_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path=base_path,
                    error_code="FHIR_CONFORMANCE_ERROR",
                    description=f"Conformance violation in {res_type}: {str(exc)}",
                    recommended_action=f"Review the schema requirements for {res_type}",
                )
            )

    @classmethod
    def _validate_clinical_semantics(
        cls,
        res_type: str,
        res: Dict[str, Any],
        base_path: str,
        res_id: Optional[str],
        issues: List[FHIRValidationIssue],
    ) -> None:
        """Validate clinical domain semantics, required fields, and coded values."""
        if res_type == "Patient":
            # Birthdate validation
            dob = res.get("birthDate")
            if dob and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(dob)):
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{base_path}.birthDate",
                        error_code="INVALID_DATE_FORMAT",
                        description=f"Invalid birthDate format '{dob}'. Must conform to YYYY, YYYY-MM, or YYYY-MM-DD",
                        recommended_action="Normalize date of birth to ISO-8601 YYYY-MM-DD format",
                    )
                )

            gender = res.get("gender")
            if gender and gender not in ["male", "female", "other", "unknown"]:
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{base_path}.gender",
                        error_code="INVALID_CODE_VALUE",
                        description=f"Invalid administrative gender '{gender}'. Must be 'male', 'female', 'other', or 'unknown'",
                        recommended_action="Map administrative gender to HL7 FHIR AdministrativeGender ValueSet",
                    )
                )

        elif res_type == "DocumentReference":
            status = res.get("status")
            if not status or status not in ["current", "superseded", "entered-in-error"]:
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{base_path}.status",
                        error_code="INVALID_STATUS",
                        description=f"Invalid DocumentReference status '{status}'. Must be 'current', 'superseded', or 'entered-in-error'",
                        recommended_action="Set status to 'current'",
                    )
                )

            content = res.get("content")
            if not content or not isinstance(content, list) or len(content) == 0:
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{base_path}.content",
                        error_code="MISSING_CONTENT",
                        description="DocumentReference must contain at least one content attachment",
                        recommended_action="Provide content attachment with data or URL",
                    )
                )

        elif res_type == "DiagnosticReport":
            status = res.get("status")
            valid_dr_status = {
                "registered", "partial", "preliminary", "final", "amended",
                "corrected", "appended", "cancelled", "entered-in-error", "unknown"
            }
            if not status or status not in valid_dr_status:
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{base_path}.status",
                        error_code="INVALID_STATUS",
                        description=f"Invalid DiagnosticReport status '{status}'",
                        recommended_action="Specify valid DiagnosticReport status (e.g. 'final')",
                    )
                )

            code = res.get("code")
            if not code or not isinstance(code, dict):
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type,
                        resource_id=res_id,
                        severity=ValidationSeverity.ERROR,
                        fhir_path=f"{base_path}.code",
                        error_code="MISSING_MANDATORY_FIELD",
                        description="DiagnosticReport missing mandatory 'code' CodeableConcept",
                        recommended_action="Provide LOINC or clinical coding in DiagnosticReport.code",
                    )
                )

    @classmethod
    def _verify_entry_references(
        cls,
        res: Dict[str, Any],
        entry_path: str,
        expected_patient_id: Optional[str],
        bundle_index: Set[Tuple[str, str]],
        issues: List[FHIRValidationIssue],
    ) -> None:
        """Inspect resource references for cross-patient leakage and dangling pointers."""
        res_type = res.get("resourceType")
        res_id = res.get("id")

        subj = res.get("subject")
        has_valid_ref = False
        if isinstance(subj, dict):
            ref_str = subj.get("reference")
            if ref_str:
                ref_id = extract_reference_id(ref_str)
                if ref_id:
                    has_valid_ref = True
                    if expected_patient_id and str(ref_id) != str(expected_patient_id):
                        issues.append(
                            FHIRValidationIssue(
                                resource_type=res_type or "Unknown",
                                resource_id=res_id,
                                severity=ValidationSeverity.ERROR,
                                fhir_path=f"{entry_path}.resource.subject.reference",
                                error_code="CROSS_PATIENT_REFERENCE_VIOLATION",
                                description=f"Resource {res_type}/{res_id} references Patient/{ref_id}, but bundle belongs to Patient/{expected_patient_id}",
                                recommended_action=f"Ensure all subject references in this bundle resolve strictly to Patient/{expected_patient_id}",
                            )
                        )
        if not has_valid_ref and res_type in ["DocumentReference", "DiagnosticReport", "Encounter", "Observation"]:
            issues.append(
                FHIRValidationIssue(
                    resource_type=res_type or "Unknown",
                    resource_id=res_id,
                    severity=ValidationSeverity.ERROR,
                    fhir_path=f"{entry_path}.resource.subject",
                    error_code="MISSING_SUBJECT_REFERENCE",
                    description=f"{res_type} is missing required 'subject' reference to patient",
                    recommended_action=f"Add subject reference {{\"reference\": \"Patient/{expected_patient_id or 'patient-id'}\"}}",
                )
            )

        enc_ref_str = None
        if isinstance(res.get("encounter"), dict):
            enc_ref_str = res["encounter"].get("reference")
        elif isinstance(res.get("context"), dict) and "encounter" in res["context"]:
            enc_list = res["context"]["encounter"]
            if enc_list and isinstance(enc_list[0], dict):
                enc_ref_str = enc_list[0].get("reference")

        if enc_ref_str:
            enc_id = extract_reference_id(enc_ref_str)
            if enc_id and ("Encounter", enc_id) not in bundle_index:
                issues.append(
                    FHIRValidationIssue(
                        resource_type=res_type or "Unknown",
                        resource_id=res_id,
                        severity=ValidationSeverity.WARNING,
                        fhir_path=f"{entry_path}.resource.encounter.reference",
                        error_code="UNRESOLVED_INTERNAL_REFERENCE",
                        description=f"{res_type}/{res_id} references Encounter/{enc_id} which is not included in this bundle",
                        recommended_action="Include the referenced Encounter in the Bundle or verify external accessibility",
                    )
                )
