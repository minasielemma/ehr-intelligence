"""Generator script for synthetic hospital EHR export dataset.

Generates 2,000 synthetic patients with thousands of longitudinal encounters,
conditions (ICD-10/SNOMED), observations (LOINC/UCUM), medications (RxNorm),
procedures, allergies, immunizations, coverages, claims, organizations, practitioners,
plain-text clinical notes, consolidated JSON, FHIR R4 Bundle and NDJSON files,
along with manifest.json, checksums.sha256, and data_dictionary.json.
Packaged into hospital_ehr_export_2000.zip.
"""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import zipfile

# Set deterministic seed
random.seed(42)

FIXTURES_DIR = Path(__file__).parent
OUTPUT_DIR = FIXTURES_DIR / "synthetic_hospital_dataset"
ZIP_OUTPUT_PATH = FIXTURES_DIR / "hospital_ehr_export_2000.zip"

FIRST_NAMES_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle"]
FIRST_NAMES_M = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris"]

CONDITIONS_CATALOG = [
    ("E11.9", "http://hl7.org/fhir/sid/icd-10-cm", "Type 2 diabetes mellitus without complications"),
    ("I10", "http://hl7.org/fhir/sid/icd-10-cm", "Essential (primary) hypertension"),
    ("J45.909", "http://hl7.org/fhir/sid/icd-10-cm", "Unspecified asthma, uncomplicated"),
    ("K21.9", "http://hl7.org/fhir/sid/icd-10-cm", "Gastro-esophageal reflux disease without esophagitis"),
    ("M54.5", "http://hl7.org/fhir/sid/icd-10-cm", "Low back pain"),
    ("F41.1", "http://hl7.org/fhir/sid/icd-10-cm", "Generalized anxiety disorder"),
    ("E78.5", "http://hl7.org/fhir/sid/icd-10-cm", "Hyperlipidemia, unspecified"),
]

OBSERVATIONS_CATALOG = [
    ("8867-4", "http://loinc.org", "Heart rate", "vital-signs", "min", 60.0, 100.0),
    ("8480-6", "http://loinc.org", "Systolic blood pressure", "vital-signs", "mmHg", 110.0, 140.0),
    ("8462-4", "http://loinc.org", "Diastolic blood pressure", "vital-signs", "mmHg", 70.0, 90.0),
    ("8310-5", "http://loinc.org", "Body temperature", "vital-signs", "Cel", 36.5, 37.3),
    ("2339-0", "http://loinc.org", "Glucose [Mass/volume] in Blood", "laboratory", "mg/dL", 80.0, 130.0),
    ("4548-4", "http://loinc.org", "Hemoglobin A1c/Hemoglobin.total in Blood", "laboratory", "%", 5.2, 7.8),
]

MEDICATIONS_CATALOG = [
    ("866439", "http://www.nlm.nih.gov/research/umls/rxnorm", "Metformin hydrochloride 500 MG Oral Tablet", "oral", 500.0, "mg", "twice daily"),
    ("197361", "http://www.nlm.nih.gov/research/umls/rxnorm", "Amlodipine 5 MG Oral Tablet", "oral", 5.0, "mg", "daily"),
    ("311354", "http://www.nlm.nih.gov/research/umls/rxnorm", "Lisinopril 10 MG Oral Tablet", "oral", 10.0, "mg", "daily"),
    ("312961", "http://www.nlm.nih.gov/research/umls/rxnorm", "Atorvastatin 20 MG Oral Tablet", "oral", 20.0, "mg", "daily at bedtime"),
]

PROCEDURES_CATALOG = [
    ("386053000", "http://snomed.info/sct", "Evaluation procedure"),
    ("440565004", "http://snomed.info/sct", "Measurement of blood pressure"),
    ("180325003", "http://snomed.info/sct", "Blood glucose monitoring"),
]

ALLERGIES_CATALOG = [
    ("91936005", "http://snomed.info/sct", "Allergy to penicillin", "medication", "high"),
    ("300916003", "http://snomed.info/sct", "Allergy to latex", "environment", "low"),
    ("227493005", "http://snomed.info/sct", "Allergy to peanut", "food", "high"),
]

IMMUNIZATIONS_CATALOG = [
    ("208", "http://hl7.org/fhir/sid/cvx", "COVID-19, mRNA, LNP-S, PF, 30 mcg/0.3 mL dose"),
    ("140", "http://hl7.org/fhir/sid/cvx", "Influenza, seasonal, injectable, preservative free"),
    ("115", "http://hl7.org/fhir/sid/cvx", "Tdap"),
]


def generate_dataset(num_patients: int = 2000):
    """Generate all dataset files in OUTPUT_DIR and package into a ZIP file."""
    if OUTPUT_DIR.exists():
        import shutil
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    notes_dir = OUTPUT_DIR / "clinical_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating synthetic hospital EHR dataset for {num_patients} patients...")

    # 1. Organizations
    orgs = [
        {"id": "ORG-101", "name": "Metropolitan Health System", "type": "hospital", "identifier": "MHS-01", "tax_id": "12-3456789", "active": "true"},
        {"id": "ORG-102", "name": "Northside Outpatient Pavilion", "type": "clinic", "identifier": "NOP-02", "tax_id": "98-7654321", "active": "true"},
    ]
    with open(OUTPUT_DIR / "organizations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(orgs[0].keys()))
        w.writeheader()
        w.writerows(orgs)

    # 2. Practitioners
    practitioners = []
    for i in range(1, 11):
        practitioners.append({
            "id": f"PRAC-{i:03d}",
            "npi": f"19876543{i:02d}",
            "first_name": random.choice(FIRST_NAMES_F + FIRST_NAMES_M),
            "last_name": random.choice(LAST_NAMES),
            "gender": "female" if i % 2 == 0 else "male",
            "qualification_code": "207Q00000X",
            "qualification_system": "http://nucc.org/provider-taxonomy",
            "qualification_display": "Family Medicine Physician",
            "active": "true",
        })
    with open(OUTPUT_DIR / "practitioners.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(practitioners[0].keys()))
        w.writeheader()
        w.writerows(practitioners)

    # 3. Patients, Encounters, Clinical Events, Financial Records
    patients = []
    encounters = []
    conditions = []
    observations = []
    medications = []
    procedures = []
    allergies = []
    immunizations = []
    coverages = []
    claims = []

    for idx in range(1, num_patients + 1):
        mrn = f"MRN-{idx:06d}"
        gender = "female" if idx % 2 == 0 else "male"
        fname = random.choice(FIRST_NAMES_F if gender == "female" else FIRST_NAMES_M)
        mname = random.choice(["A.", "B.", "C.", "D.", "E.", "M."])
        lname = random.choice(LAST_NAMES)
        birth_year = random.randint(1945, 2005)
        birth_month = random.randint(1, 12)
        birth_day = random.randint(1, 28)
        dob = f"{birth_year:04d}-{birth_month:02d}-{birth_day:02d}"

        patients.append({
            "id": f"PAT-{idx:06d}",
            "mrn": mrn,
            "first_name": fname,
            "middle_name": mname,
            "last_name": lname,
            "dob": dob,
            "gender": gender,
            "phone": f"555-{random.randint(100, 999)}-{random.randint(1000, 9999)}",
            "email": f"{fname.lower()}.{lname.lower()}{idx}@example.com",
            "address_line": f"{random.randint(100, 999)} Healthcare Ave",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62701",
        })

        # Coverage
        cov_id = f"COV-{idx:06d}"
        coverages.append({
            "id": cov_id,
            "patient_id": mrn,
            "subscriber_id": f"SUB-{idx:06d}",
            "beneficiary_id": mrn,
            "relationship_to_subscriber": "self",
            "status": "active",
            "type": "health_insurance",
            "period_start": f"{birth_year + 18:04d}-01-01",
            "period_end": "2030-12-31",
            "payor_id": "PAYOR-01",
            "payor_name": "Blue Cross Blue Shield",
        })

        # Encounters (2 to 4 longitudinal visits per patient)
        num_encs = random.randint(2, 4)
        for e_num in range(1, num_encs + 1):
            enc_id = f"ENC-{idx:06d}-{e_num}"
            enc_year = random.randint(2022, 2024)
            enc_month = random.randint(1, 12)
            enc_day = random.randint(1, 28)
            enc_date = f"{enc_year:04d}-{enc_month:02d}-{enc_day:02d}"
            prac = random.choice(practitioners)
            org = random.choice(orgs)

            encounters.append({
                "id": enc_id,
                "patient_id": mrn,
                "practitioner_id": prac["id"],
                "organization_id": org["id"],
                "status": "finished",
                "class_code": "AMB",
                "type": "Outpatient Follow-up",
                "start_time": f"{enc_date}T09:00:00Z",
                "end_time": f"{enc_date}T10:00:00Z",
                "reason_code": "Z00.00",
                "reason_display": "Encounter for general adult medical examination",
                "service_provider": org["name"],
            })

            # Conditions for this encounter
            cond_item = random.choice(CONDITIONS_CATALOG)
            conditions.append({
                "id": f"COND-{idx:06d}-{e_num}",
                "patient_id": mrn,
                "encounter_id": enc_id,
                "code": cond_item[0],
                "code_system": cond_item[1],
                "display": cond_item[2],
                "clinical_status": "active",
                "verification_status": "confirmed",
                "category": "encounter-diagnosis",
                "severity": "moderate",
                "onset_date": enc_date,
                "recorded_date": enc_date,
            })

            # Observations (Vitals / Labs)
            for obs_item in OBSERVATIONS_CATALOG[:3]:
                val = round(random.uniform(obs_item[5], obs_item[6]), 1)
                observations.append({
                    "id": f"OBS-{idx:06d}-{e_num}-{obs_item[0]}",
                    "patient_id": mrn,
                    "encounter_id": enc_id,
                    "code": obs_item[0],
                    "code_system": obs_item[1],
                    "display": obs_item[2],
                    "category": obs_item[3],
                    "status": "final",
                    "value_quantity": val,
                    "value_unit": obs_item[4],
                    "value_string": f"{val} {obs_item[4]}",
                    "effective_date": f"{enc_date}T09:15:00Z",
                    "reference_range_low": obs_item[5],
                    "reference_range_high": obs_item[6],
                    "interpretation": "N",
                })

            # Medications
            med_item = random.choice(MEDICATIONS_CATALOG)
            med_req_id = f"MED-{idx:06d}-{e_num}"
            medications.append({
                "id": med_req_id,
                "patient_id": mrn,
                "encounter_id": enc_id,
                "practitioner_id": prac["id"],
                "code": med_item[0],
                "code_system": med_item[1],
                "display": med_item[2],
                "status": "active",
                "intent": "order",
                "dosage_instruction": f"Take 1 tablet {med_item[6]}",
                "route": med_item[3],
                "dose_quantity": med_item[4],
                "dose_unit": med_item[5],
                "frequency": med_item[6],
                "authored_on": enc_date,
            })

            # Procedures
            proc_item = random.choice(PROCEDURES_CATALOG)
            procedures.append({
                "id": f"PROC-{idx:06d}-{e_num}",
                "patient_id": mrn,
                "encounter_id": enc_id,
                "code": proc_item[0],
                "code_system": proc_item[1],
                "display": proc_item[2],
                "status": "completed",
                "performed_date": enc_date,
                "outcome": "Successful",
            })

            # Claim for the encounter
            claims.append({
                "id": f"CLM-{idx:06d}-{e_num}",
                "patient_id": mrn,
                "encounter_id": enc_id,
                "coverage_id": cov_id,
                "status": "active",
                "type": "professional",
                "use": "claim",
                "created_date": enc_date,
                "total_amount": round(random.uniform(150.0, 450.0), 2),
                "currency": "USD",
            })

        # Allergies
        if idx % 3 == 0:
            alg_item = random.choice(ALLERGIES_CATALOG)
            allergies.append({
                "id": f"ALG-{idx:06d}",
                "patient_id": mrn,
                "code": alg_item[0],
                "code_system": alg_item[1],
                "display": alg_item[2],
                "clinical_status": "active",
                "verification_status": "confirmed",
                "category": alg_item[3],
                "criticality": alg_item[4],
                "recorded_date": "2023-01-15",
                "reaction_manifestation": "Skin rash and hives",
            })

        # Immunizations
        imm_item = random.choice(IMMUNIZATIONS_CATALOG)
        immunizations.append({
            "id": f"IMM-{idx:06d}",
            "patient_id": mrn,
            "encounter_id": f"ENC-{idx:06d}-1",
            "vaccine_code": imm_item[0],
            "vaccine_code_system": imm_item[1],
            "vaccine_display": imm_item[2],
            "status": "completed",
            "occurrence_date": "2023-10-01",
            "primary_source": "true",
            "lot_number": f"LOT-{random.randint(10000, 99999)}",
        })

        # Generate sample plain-text clinical notes for first 50 patients
        if idx <= 50:
            note_content = (
                f"PATIENT NAME: {lname}, {fname}\n"
                f"MRN: {mrn}\n"
                f"DOB: {dob}\n"
                f"GENDER: {gender.capitalize()}\n"
                f"ENCOUNTER ID: ENC-{idx:06d}-1\n"
                f"DATE: 2024-01-15\n"
                f"DOCUMENT TYPE: Progress Note\n\n"
                f"SUBJECTIVE:\n"
                f"Patient presents for routine follow-up. Vital signs stable.\n\n"
                f"ASSESSMENT & PLAN:\n"
                f"Continue current medical regimen. Re-evaluate in 6 months.\n"
            )
            (notes_dir / f"note_{mrn}.txt").write_text(note_content, encoding="utf-8")

    # Write CSV Domain Files
    def write_csv(filename: str, rows: list):
        if not rows:
            return
        with open(OUTPUT_DIR / filename, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write_csv("patients.csv", patients)
    write_csv("coverages.csv", coverages)
    write_csv("encounters.csv", encounters)
    write_csv("conditions.csv", conditions)
    write_csv("observations.csv", observations)
    write_csv("medication_requests.csv", medications)
    write_csv("procedures.csv", procedures)
    write_csv("allergies.csv", allergies)
    write_csv("immunizations.csv", immunizations)
    write_csv("claims.csv", claims)

    # 4. Consolidated JSON Export (first 200 patients)
    consolidated_data = {
        "hospital_name": "Metropolitan Health System",
        "export_timestamp": "2026-11-20T00:00:00Z",
        "organizations": orgs,
        "practitioners": practitioners[:5],
        "patients": [
            {
                "id": p["id"],
                "mrn": p["mrn"],
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "dob": p["dob"],
                "gender": p["gender"],
                "encounters": [e for e in encounters if e["patient_id"] == p["mrn"]],
                "conditions": [c for c in conditions if c["patient_id"] == p["mrn"]],
                "observations": [o for o in observations if o["patient_id"] == p["mrn"]],
            }
            for p in patients[:200]
        ]
    }
    with open(OUTPUT_DIR / "patients_consolidated.json", "w", encoding="utf-8") as f:
        json.dump(consolidated_data, f, indent=2)

    # 5. FHIR R4 Bundle (transaction containing Patient, Encounter, Condition, Observation)
    sample_p = patients[0]
    fhir_bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": sample_p["mrn"],
                    "identifier": [
                        {"system": "http://hospital.example.org/mrn", "value": sample_p["mrn"], "type": {"coding": [{"code": "MR"}]}}
                    ],
                    "name": [{"family": sample_p["last_name"], "given": [sample_p["first_name"]]}],
                    "gender": sample_p["gender"],
                    "birthDate": sample_p["dob"],
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "ENC-SAMPLE-01",
                    "status": "finished",
                    "class": {"code": "AMB", "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode"},
                    "subject": {"reference": f"Patient/{sample_p['mrn']}"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "COND-SAMPLE-01",
                    "clinicalStatus": {"coding": [{"code": "active", "system": "http://terminology.hl7.org/CodeSystem/condition-clinical"}]},
                    "verificationStatus": {"coding": [{"code": "confirmed", "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status"}]},
                    "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10", "display": "Essential hypertension"}]},
                    "subject": {"reference": f"Patient/{sample_p['mrn']}"},
                    "encounter": {"reference": "Encounter/ENC-SAMPLE-01"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "OBS-SAMPLE-01",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                    "subject": {"reference": f"Patient/{sample_p['mrn']}"},
                    "encounter": {"reference": "Encounter/ENC-SAMPLE-01"},
                    "valueQuantity": {"value": 72.0, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"},
                }
            }
        ]
    }
    with open(OUTPUT_DIR / "fhir_bundle.json", "w", encoding="utf-8") as f:
        json.dump(fhir_bundle, f, indent=2)

    # 6. FHIR NDJSON (Patient.ndjson)
    with open(OUTPUT_DIR / "Patient.ndjson", "w", encoding="utf-8") as f:
        for p in patients[:50]:
            f.write(json.dumps({
                "resourceType": "Patient",
                "id": p["mrn"],
                "identifier": [{"system": "http://hospital.example.org/mrn", "value": p["mrn"], "type": {"coding": [{"code": "MR"}]}}],
                "name": [{"family": p["last_name"], "given": [p["first_name"]]}],
                "gender": p["gender"],
                "birthDate": p["dob"],
            }) + "\n")

    # 7. Data Dictionary
    data_dict = {
        "version": "1.0.0",
        "hospital": "Metropolitan Health System",
        "domains": {
            "organizations": {"description": "Hospital facilities and operational clinics"},
            "practitioners": {"description": "Healthcare providers and physician registries"},
            "patients": {"description": "Patient demographics and identity records"},
            "coverages": {"description": "Insurance policies and health plan subscriptions"},
            "encounters": {"description": "Longitudinal ambulatory and inpatient clinical visits"},
            "conditions": {"description": "Diagnoses encoded in ICD-10-CM"},
            "observations": {"description": "Vitals and laboratory results in LOINC and UCUM"},
            "medication_requests": {"description": "Outpatient prescriptions encoded in RxNorm"},
            "procedures": {"description": "Diagnostic and surgical procedures in SNOMED CT"},
            "allergies": {"description": "Allergy and intolerance records in SNOMED CT"},
            "immunizations": {"description": "Vaccine administration records in CVX"},
            "claims": {"description": "Financial billing claims linked to encounters"},
        }
    }
    with open(OUTPUT_DIR / "data_dictionary.json", "w", encoding="utf-8") as f:
        json.dump(data_dict, f, indent=2)

    # 8. Compute Checksums & Write checksums.sha256 and manifest.json
    checksum_lines = []
    manifest_files = []

    for item_path in sorted(OUTPUT_DIR.rglob("*")):
        if item_path.is_file() and item_path.name not in ["manifest.json", "checksums.sha256"]:
            rel_name = str(item_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
            h = hashlib.sha256()
            h.update(item_path.read_bytes())
            sha = h.hexdigest().lower()
            checksum_lines.append(f"{sha}  {rel_name}")
            manifest_files.append({"filename": rel_name, "sha256": sha, "size_bytes": item_path.stat().st_size})

    with open(OUTPUT_DIR / "checksums.sha256", "w", encoding="utf-8") as f:
        f.write("\n".join(checksum_lines) + "\n")

    manifest = {
        "dataset_name": "Metropolitan Hospital Comprehensive EHR Export",
        "export_timestamp": "2026-11-20T00:00:00Z",
        "provider": "Metropolitan Health System",
        "source_system": "metropolitan_ehr",
        "patient_count": num_patients,
        "files": manifest_files,
    }
    with open(OUTPUT_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # 9. Create Zip Archive
    print(f"Packaging into {ZIP_OUTPUT_PATH}...")
    with zipfile.ZipFile(ZIP_OUTPUT_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in OUTPUT_DIR.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, arcname=str(file_path.relative_to(OUTPUT_DIR)))

    print(f"Dataset successfully created: {ZIP_OUTPUT_PATH} ({ZIP_OUTPUT_PATH.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    generate_dataset(num_patients=2000)
