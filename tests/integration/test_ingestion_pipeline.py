"""End-to-end integration tests for multi-format EHR ingestion pipeline."""

import io
import json
import pytest
from httpx import AsyncClient
from fastapi import status
from sqlalchemy import select

from app.models.database import get_session_factory, init_db
from app.models.ingestion import ClinicalRecordModel, ConditionModel, ObservationModel, PatientModel
from app.repositories.domain_repository import DomainRepository


@pytest.mark.asyncio
async def test_full_json_ingestion_workflow(async_client: AsyncClient, test_settings) -> None:
    """Verify complete JSON ingestion lifecycle: POST -> Job Status -> Report -> Paginated Records."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    payload = {
        "source_system": "metro_health",
        "idempotency_key": "idemp-test-json-001",
        "records": [
            {
                "id": "METRO-REC-1",
                "mrn": "  00099812  ",
                "first_name": "  Clara  ",
                "last_name": "  Barton  ",
                "dob": "1978-12-25",
                "gender": "F",
                "clinical_text": "Patient presents with persistent cough.\r\nBP: 120/80 mmHg. No acute distress.\x00",
            },
            {
                "id": "METRO-REC-2",
                "mrn": "00099813",
                "first_name": "Florence",
                "last_name": "Nightingale",
                "dob": "1982-05-12",
                "gender": "Female",
                "clinical_text": "Follow-up visit. Labs: HbA1c 5.6%. Prescribed Metformin 500mg BID.",
            },
        ],
    }

    # 1. Submit JSON ingestion
    resp = await async_client.post("/api/v1/ingestion/json", json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    job_data = resp.json()
    job_id = job_data["job_id"]
    assert job_data["status"] == "COMPLETED"
    assert job_data["total_records"] == 2
    assert job_data["successful_records"] == 2
    assert job_data["rejected_records"] == 0

    # 2. Check Job Status endpoint
    status_resp = await async_client.get(f"/api/v1/ingestion/jobs/{job_id}")
    assert status_resp.status_code == status.HTTP_200_OK
    assert status_resp.json()["job_id"] == job_id
    assert status_resp.json()["status"] == "COMPLETED"

    # 3. Check Job Report endpoint
    report_resp = await async_client.get(f"/api/v1/ingestion/jobs/{job_id}/report")
    assert report_resp.status_code == status.HTTP_200_OK
    rep_data = report_resp.json()
    assert rep_data["reconciliation_summary"]["successful"] == 2
    assert len(rep_data["recent_audit_events"]) > 0

    # 4. Check Records pagination endpoint
    records_resp = await async_client.get(f"/api/v1/ingestion/jobs/{job_id}/records?page=1&page_size=10")
    assert records_resp.status_code == status.HTTP_200_OK
    rec_data = records_resp.json()
    assert rec_data["total"] == 2
    assert len(rec_data["items"]) == 2
    assert rec_data["items"][0]["status"] == "NORMALIZED"
    assert "120/80 mmHg" in rec_data["items"][0]["cleaned_text"]


@pytest.mark.asyncio
async def test_idempotent_ingestion_replay(async_client: AsyncClient, test_settings) -> None:
    """Verify that repeated submissions with the same idempotency key return the original job without reprocessing."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    payload = {
        "source_system": "st_jude",
        "idempotency_key": "fixed-idempotency-key-xyz",
        "records": [
            {
                "id": "SJ-01",
                "mrn": "004812",
                "first_name": "Arthur",
                "last_name": "Conan",
                "dob": "1960-05-22",
                "gender": "M",
                "clinical_text": "Physical examination completed.",
            }
        ],
    }

    resp1 = await async_client.post("/api/v1/ingestion/json", json=payload)
    assert resp1.status_code == status.HTTP_201_CREATED
    job_id_1 = resp1.json()["job_id"]

    resp2 = await async_client.post("/api/v1/ingestion/json", json=payload)
    assert resp2.status_code == status.HTTP_201_CREATED
    job_id_2 = resp2.json()["job_id"]

    # Must be the exact same job
    assert job_id_1 == job_id_2


@pytest.mark.asyncio
async def test_csv_upload_ingestion(async_client: AsyncClient, test_settings) -> None:
    """Verify CSV file upload, chunked parsing, and demographic normalization."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    csv_content = (
        "mrn,first_name,last_name,dob,gender,clinical_text\n"
        "001920,Grace,Hopper,1956-12-09,F,Computerized tomography review.\n"
        "001921,Ada,Lovelace,1965-11-27,Female,Algorithmically monitored recovery.\n"
    ).encode("utf-8")

    files = {"file": ("ehr_patients.csv", csv_content, "text/csv")}
    data = {"source_system": "naval_medical"}

    response = await async_client.post("/api/v1/ingestion/upload", files=files, data=data)
    assert response.status_code == status.HTTP_201_CREATED
    res_data = response.json()
    assert res_data["total_records"] == 2
    assert res_data["successful_records"] == 2
    assert res_data["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_text_clinical_note_upload(async_client: AsyncClient, test_settings) -> None:
    """Verify Plain-Text document upload and extraction."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    note_text = """
    PATIENT NAME: Lovelace, Augusta
    MRN: 8847192
    DOB: 1980-04-18
    GENDER: Female
    REPORT TYPE: Progress Note

    CLINICAL IMPRESSION:
    Patient is recovering well. No acute cardiopulmonary symptoms.
    Vitals: BP 118/76 mmHg, HR 68, SpO2 99%.
    """.strip().encode("utf-8")

    files = {"file": ("progress_note.txt", note_text, "text/plain")}
    data = {"source_system": "outpatient_clinic"}

    response = await async_client.post("/api/v1/ingestion/upload", files=files, data=data)
    assert response.status_code == status.HTTP_201_CREATED
    res_data = response.json()
    assert res_data["total_records"] == 1
    assert res_data["successful_records"] == 1


@pytest.mark.asyncio
async def test_provenance_csv_upload_ingestion(async_client: AsyncClient, test_settings) -> None:
    """Verify standalone provenance domain CSV file upload without requiring patient demographics."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    prov_csv = (
        "provenance_id,patient_id,target_resource_type,target_resource_id,recorded_at,agent_id,activity,signature_status\n"
        "PROV-000001,PAT-000001,Patient,PAT-000001,2026-11-21T00:00:00,SYSTEM-SYNTHETIC,record-generation,not-signed-synthetic\n"
        "PROV-000002,PAT-000002,Patient,PAT-000002,2026-11-21T00:00:00,SYSTEM-SYNTHETIC,record-generation,not-signed-synthetic\n"
    ).encode("utf-8")

    files = {"file": ("provenances.csv", prov_csv, "text/csv")}
    data = {"source_system": "audit_system"}

    response = await async_client.post("/api/v1/ingestion/upload", files=files, data=data)
    assert response.status_code == status.HTTP_201_CREATED
    res_data = response.json()
    assert res_data["total_records"] == 2
    assert res_data["successful_records"] == 2
    assert res_data["rejected_records"] == 0
    assert res_data["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_identity_conflict_detection_workflow(async_client: AsyncClient, test_settings) -> None:
    """Verify identity conflict is flagged when identical MRN in same system has conflicting demographics."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    # 1. Ingest original patient
    payload1 = {
        "source_system": "conflict_center",
        "records": [
            {
                "id": "INIT-01",
                "mrn": "SHARED-MRN-999",
                "first_name": "Marie",
                "last_name": "Curie",
                "dob": "1977-11-07",
                "gender": "female",
                "clinical_text": "Oncology consultation.",
            }
        ],
    }
    resp1 = await async_client.post("/api/v1/ingestion/json", json=payload1)
    assert resp1.status_code == status.HTTP_201_CREATED
    assert resp1.json()["successful_records"] == 1

    # 2. Ingest conflicting record with same MRN in conflict_center but different name and DOB
    payload2 = {
        "source_system": "conflict_center",
        "records": [
            {
                "id": "CONFLICT-02",
                "mrn": "SHARED-MRN-999",
                "first_name": "Pierre",
                "last_name": "Curie",
                "dob": "1979-05-15",
                "gender": "male",
                "clinical_text": "Orthopedic follow-up.",
            }
        ],
    }
    resp2 = await async_client.post("/api/v1/ingestion/json", json=payload2)
    assert resp2.status_code == status.HTTP_201_CREATED
    data2 = resp2.json()
    assert data2["conflict_records"] == 1
    assert data2["status"] == "COMPLETED_WITH_WARNINGS"

    # Verify record status is MANUAL_REVIEW_REQUIRED
    job_id = data2["job_id"]
    rec_resp = await async_client.get(f"/api/v1/ingestion/jobs/{job_id}/records")
    assert rec_resp.status_code == status.HTTP_200_OK
    assert rec_resp.json()["items"][0]["status"] == "MANUAL_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_universal_auto_patient_linking_to_existing_patient(async_client: AsyncClient, test_settings) -> None:
    """Verify that any domain data referencing a patient ID automatically links to an existing patient."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    # 1. Ingest existing canonical patient
    payload = {
        "source_system": "hospital_alpha",
        "records": [
            {
                "id": "PAT-INIT-01",
                "mrn": "MRN-ADA-100",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "dob": "1815-12-10",
                "gender": "female",
                "clinical_text": "Pioneer of computing consultation.",
            }
        ],
    }
    resp1 = await async_client.post("/api/v1/ingestion/json", json=payload)
    assert resp1.status_code == status.HTTP_201_CREATED
    assert resp1.json()["successful_records"] == 1

    # 2. Upload observations CSV referencing this MRN in patient_id
    obs_csv = (
        "observation_id,patient_id,encounter_id,category,code,code_system,display,value_numeric,unit,status,effective_date\n"
        "OBS-001,MRN-ADA-100,ENC-999,vital-signs,8867-4,http://loinc.org,Heart rate,72,bpm,final,2026-11-21T10:00:00\n"
    )
    files = {"file": ("observations.csv", io.BytesIO(obs_csv.encode("utf-8")), "text/csv")}
    data = {"source_system": "hospital_alpha"}
    resp2 = await async_client.post("/api/v1/ingestion/upload", files=files, data=data)
    assert resp2.status_code == status.HTTP_201_CREATED
    res2 = resp2.json()
    assert res2["total_records"] == 1
    assert res2["successful_records"] == 1
    assert res2["rejected_records"] == 0

    # 3. Verify in DB that ObservationModel is linked to Ada's patient ID
    async with get_session_factory(test_settings.sqlite_url)() as session:
        pat_stmt = select(PatientModel).where(PatientModel.mrn == "MRN-ADA-100")
        pat_res = await session.execute(pat_stmt)
        pat = pat_res.scalars().first()
        assert pat is not None

        obs_stmt = select(ObservationModel).where(ObservationModel.source_id == "OBS-001")
        obs_res = await session.execute(obs_stmt)
        obs = obs_res.scalars().first()
        assert obs is not None
        assert obs.patient_id == pat.id


@pytest.mark.asyncio
async def test_out_of_order_domain_record_placeholder_and_subsequent_enrichment(async_client: AsyncClient, test_settings) -> None:
    """Verify out-of-order domain ingestion creates placeholder patient and subsequent demographics enrich it."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    # 1. Ingest conditions CSV referencing an uningested patient
    cond_csv = (
        "condition_id,patient_id,code,code_system,display,clinical_status,verification_status\n"
        "COND-999,PAT-ROSALIND-777,E11.9,http://hl7.org/fhir/sid/icd-10-cm,Type 2 diabetes,active,confirmed\n"
    )
    files = {"file": ("conditions.csv", io.BytesIO(cond_csv.encode("utf-8")), "text/csv")}
    data = {"source_system": "hospital_beta"}
    resp1 = await async_client.post("/api/v1/ingestion/upload", files=files, data=data)
    assert resp1.status_code == status.HTTP_201_CREATED
    assert resp1.json()["successful_records"] == 1

    # Verify placeholder was created and condition is linked
    async with get_session_factory(test_settings.sqlite_url)() as session:
        cond_stmt = select(ConditionModel).where(ConditionModel.source_id == "COND-999")
        cond_res = await session.execute(cond_stmt)
        cond = cond_res.scalars().first()
        assert cond is not None
        assert cond.patient_id is not None
        initial_patient_id = cond.patient_id

        pat_stmt = select(PatientModel).where(PatientModel.id == initial_patient_id)
        pat_res = await session.execute(pat_stmt)
        placeholder = pat_res.scalars().first()
        assert placeholder is not None
        assert placeholder.first_name == "UNRESOLVED"

    # 2. Later, ingest the real demographic record for PAT-ROSALIND-777
    demo_payload = {
        "source_system": "hospital_beta",
        "records": [
            {
                "id": "DEMO-01",
                "mrn": "PAT-ROSALIND-777",
                "first_name": "Rosalind",
                "last_name": "Franklin",
                "dob": "1920-07-25",
                "gender": "female",
                "clinical_text": "Biophysics research record.",
            }
        ],
    }
    resp2 = await async_client.post("/api/v1/ingestion/json", json=demo_payload)
    assert resp2.status_code == status.HTTP_201_CREATED
    assert resp2.json()["successful_records"] == 1

    # Verify the patient has been enriched in-place and condition is still linked
    async with get_session_factory(test_settings.sqlite_url)() as session:
        pat_stmt = select(PatientModel).where(PatientModel.id == initial_patient_id)
        pat_res = await session.execute(pat_stmt)
        enriched = pat_res.scalars().first()
        assert enriched is not None
        assert enriched.first_name == "Rosalind"
        assert enriched.last_name == "Franklin"
        assert enriched.reconciliation_status == "MATCHED"


@pytest.mark.asyncio
async def test_unstructured_clinical_note_without_names_auto_links_by_mrn(async_client: AsyncClient, test_settings) -> None:
    """Verify messy record with only patient ID/MRN and no demographic names is auto-linked rather than rejected."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    # Ingest clinical note with only MRN (no first_name or last_name)
    payload = {
        "source_system": "hospital_gamma",
        "records": [
            {
                "id": "NOTE-001",
                "mrn": "MRN-NO-DEMO-555",
                "clinical_text": "Pathology biopsy report: benign tissue.",
            }
        ],
    }
    resp = await async_client.post("/api/v1/ingestion/json", json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["total_records"] == 1
    assert data["successful_records"] == 1
    assert data["rejected_records"] == 0

    # Verify clinical record in DB is linked to the created placeholder patient
    async with get_session_factory(test_settings.sqlite_url)() as session:
        rec_stmt = select(ClinicalRecordModel).where(ClinicalRecordModel.source_record_id == "NOTE-001")
        rec_res = await session.execute(rec_stmt)
        rec = rec_res.scalars().first()
        assert rec is not None
        assert rec.patient_id is not None
        assert rec.status == "NORMALIZED"

        pat_stmt = select(PatientModel).where(PatientModel.id == rec.patient_id)
        pat_res = await session.execute(pat_stmt)
        pat = pat_res.scalars().first()
        assert pat is not None
        assert pat.mrn == "MRN-NO-DEMO-555"


@pytest.mark.asyncio
async def test_multi_tenant_mrn_source_scoping(async_client: AsyncClient, test_settings) -> None:
    """Verify that identical MRNs across distinct hospital source systems are properly isolated and scoped."""
    await init_db(database_path=test_settings.DATABASE_PATH)

    # Ingest MRN "MRN-SHARED-999" for hospital_alpha
    resp_alpha = await async_client.post(
        "/api/v1/ingestion/json",
        json={
            "source_system": "hospital_alpha",
            "records": [
                {
                    "id": "ALPHA-PAT-1",
                    "mrn": "MRN-SHARED-999",
                    "first_name": "Alice",
                    "last_name": "Alpha",
                    "dob": "1980-01-01",
                    "gender": "F",
                    "clinical_text": "Routine checkup at Hospital Alpha.",
                }
            ],
        },
    )
    assert resp_alpha.status_code == status.HTTP_201_CREATED

    # Ingest same MRN "MRN-SHARED-999" for hospital_beta
    resp_beta = await async_client.post(
        "/api/v1/ingestion/json",
        json={
            "source_system": "hospital_beta",
            "records": [
                {
                    "id": "BETA-PAT-1",
                    "mrn": "MRN-SHARED-999",
                    "first_name": "Bob",
                    "last_name": "Beta",
                    "dob": "1975-06-15",
                    "gender": "M",
                    "clinical_text": "Cardiology consultation at Hospital Beta.",
                }
            ],
        },
    )
    assert resp_beta.status_code == status.HTTP_201_CREATED

    # Query source maps for each tenant
    async with get_session_factory(test_settings.sqlite_url)() as session:
        domain_repo = DomainRepository(session)
        map_alpha = await domain_repo.get_patient_source_map("hospital_alpha")
        map_beta = await domain_repo.get_patient_source_map("hospital_beta")

        assert "MRN-SHARED-999" in map_alpha
        assert "MRN-SHARED-999" in map_beta

        patient_alpha_id = map_alpha["MRN-SHARED-999"]
        patient_beta_id = map_beta["MRN-SHARED-999"]

        # Ensure distinct patient records were created and mapped
        assert patient_alpha_id != patient_beta_id

        # Verify hospital_alpha mapping points to Alice
        stmt_a = select(PatientModel).where(PatientModel.id == patient_alpha_id)
        pat_a = (await session.execute(stmt_a)).scalars().first()
        assert pat_a is not None
        assert pat_a.source_system == "hospital_alpha"
        assert pat_a.first_name == "Alice"

        # Verify hospital_beta mapping points to Bob
        stmt_b = select(PatientModel).where(PatientModel.id == patient_beta_id)
        pat_b = (await session.execute(stmt_b)).scalars().first()
        assert pat_b is not None
        assert pat_b.source_system == "hospital_beta"
        assert pat_b.first_name == "Bob"

