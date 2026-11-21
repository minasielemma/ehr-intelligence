"""Unit tests for HL7 FHIR R4 Bundle Builder and Reference Graph Engine."""

import pytest

from app.core.exceptions import ValidationException
from app.fhir.bundler import FHIRBundleBuilder


def test_bundle_builder_collection_bundle():
    """Verify FHIRBundleBuilder constructs a compliant collection bundle with sorted entries."""
    builder = FHIRBundleBuilder(patient_id="pat-100", bundle_type="collection")

    doc_res = {
        "resourceType": "DocumentReference",
        "id": "doc-1",
        "status": "current",
        "docStatus": "final",
        "type": {"coding": [{"system": "http://loinc.org", "code": "34108-1"}]},
        "subject": {"reference": "Patient/pat-100"},
        "content": [{"attachment": {"contentType": "text/plain", "data": "VGVzdA=="}}],
    }
    pat_res = {
        "resourceType": "Patient",
        "id": "pat-100",
        "name": [{"family": "Smith", "given": ["Alice"]}],
        "gender": "female",
    }

    # Add in reverse order: Patient must be sorted to index 0
    builder.add_resource(doc_res)
    builder.add_resource(pat_res)

    bundle = builder.build()

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert bundle["total"] == 2
    assert len(bundle["entry"]) == 2

    # First entry should be Patient
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][0]["fullUrl"].endswith("Patient/pat-100")
    assert bundle["entry"][1]["resource"]["resourceType"] == "DocumentReference"


def test_bundle_builder_transaction_bundle():
    """Verify transaction bundle entries contain correct request verbs."""
    builder = FHIRBundleBuilder(patient_id="pat-200", bundle_type="transaction")

    pat_res = {
        "resourceType": "Patient",
        "id": "pat-200",
        "name": [{"family": "Bob", "given": ["Builder"]}],
    }
    builder.add_resource(pat_res)

    bundle = builder.build()

    assert bundle["type"] == "transaction"
    entry = bundle["entry"][0]
    assert "request" in entry
    assert entry["request"]["method"] == "PUT"
    assert entry["request"]["url"] == "Patient/pat-200"


def test_bundle_builder_detects_cross_patient_leakage():
    """Verify builder rejects cross-patient references where resources target a foreign patient."""
    builder = FHIRBundleBuilder(patient_id="pat-target")

    pat_res = {
        "resourceType": "Patient",
        "id": "pat-target",
        "name": [{"family": "Target"}],
    }
    # Foreign patient resource
    foreign_doc = {
        "resourceType": "DocumentReference",
        "id": "doc-foreign",
        "status": "current",
        "subject": {"reference": "Patient/pat-FOREIGN-VIOLATION"},
        "content": [{"attachment": {"contentType": "text/plain", "data": "WA=="}}],
    }

    builder.add_resource(pat_res)
    builder.add_resource(foreign_doc)

    with pytest.raises(ValidationException) as exc_info:
        builder.build()

    assert "Cross-patient reference in DocumentReference/doc-foreign" in str(exc_info.value)
    assert "Patient/pat-FOREIGN-VIOLATION" in str(exc_info.value)


def test_bundle_builder_multiple_patients_isolated():
    """Verify building bundles for distinct patients maintains complete demographic isolation."""
    builder1 = FHIRBundleBuilder(patient_id="patient-A")
    builder1.add_resource({
        "resourceType": "Patient",
        "id": "patient-A",
        "name": [{"family": "Alpha"}],
    })
    builder1.add_resource({
        "resourceType": "Observation",
        "id": "obs-A",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "subject": {"reference": "Patient/patient-A"},
    })

    builder2 = FHIRBundleBuilder(patient_id="patient-B")
    builder2.add_resource({
        "resourceType": "Patient",
        "id": "patient-B",
        "name": [{"family": "Beta"}],
    })
    builder2.add_resource({
        "resourceType": "Observation",
        "id": "obs-B",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "subject": {"reference": "Patient/patient-B"},
    })

    bundle1 = builder1.build()
    bundle2 = builder2.build()

    assert bundle1["entry"][0]["resource"]["id"] == "patient-A"
    assert bundle1["entry"][1]["resource"]["subject"]["reference"] == "Patient/patient-A"

    assert bundle2["entry"][0]["resource"]["id"] == "patient-B"
    assert bundle2["entry"][1]["resource"]["subject"]["reference"] == "Patient/patient-B"


def test_bundle_builder_dangling_internal_reference_warning():
    """Verify detection of dangling internal references (e.g. Encounter not in bundle)."""
    builder = FHIRBundleBuilder(patient_id="pat-100")
    builder.add_resource({
        "resourceType": "Patient",
        "id": "pat-100",
        "name": [{"family": "Smith"}],
    })
    # Add an encounter to builder, but document references missing encounter
    builder.add_resource({
        "resourceType": "Encounter",
        "id": "enc-actual",
        "status": "finished",
        "class": {"code": "AMB", "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode"},
        "subject": {"reference": "Patient/pat-100"},
    })
    builder.add_resource({
        "resourceType": "DocumentReference",
        "id": "doc-dangling",
        "status": "current",
        "subject": {"reference": "Patient/pat-100"},
        "context": {"encounter": [{"reference": "Encounter/enc-MISSING"}]},
        "content": [{"attachment": {"contentType": "text/plain", "data": "WA=="}}],
    })

    is_valid, issues = builder.verify_internal_references()
    assert is_valid is False
    assert len(issues) == 1
    assert "Encounter/enc-MISSING not present in bundle" in issues[0]
