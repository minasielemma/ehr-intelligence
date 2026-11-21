"""Unit tests for FHIR R4 Bundle storage (SQLite repository & atomic file store)."""

import json
import os
from pathlib import Path
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StorageException
from app.fhir.storage import FHIRBundleFileStorage
from app.models.database import get_session_factory, init_db
from app.models.ingestion import PatientModel
from app.repositories.fhir_bundle_repository import FHIRBundleRepository, compute_bundle_hash
from app.repositories.patient_repository import PatientRepository


@pytest.fixture
async def db_session(tmp_path) -> AsyncSession:
    """Provide an isolated SQLite database session for unit testing."""
    db_path = str(tmp_path / "test_fhir_storage.db")
    await init_db(database_path=db_path)
    session_factory = get_session_factory(f"sqlite+aiosqlite:///{db_path}")
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_fhir_bundle_repository_save_and_retrieve(db_session: AsyncSession):
    """Verify persisting a bundle and retrieving it by bundle_id, patient_id, and MRN."""
    pat_repo = PatientRepository(db_session)
    bundle_repo = FHIRBundleRepository(db_session)

    # 1. Create patient record
    patient = PatientModel(
        id="pat-store-001",
        source_system="hospital_a",
        mrn="MRN-STORE-001",
        first_name="Marcus",
        last_name="Brody",
        administrative_gender="male",
    )
    await pat_repo.create_patient(patient, [])

    # 2. Persist FHIR Bundle
    bundle_data = {
        "resourceType": "Bundle",
        "id": "bundle-store-001",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-store-001",
                    "name": [{"family": "Brody", "given": ["Marcus"]}],
                }
            }
        ],
    }

    saved_bundle, is_new = await bundle_repo.save_bundle(
        bundle_id="bundle-store-001",
        patient_id="pat-store-001",
        patient_mrn="MRN-STORE-001",
        bundle_type="collection",
        bundle_json=bundle_data,
        status="VALID",
        resource_count=1,
    )
    await db_session.commit()

    assert is_new is True
    assert saved_bundle.version == 1
    assert saved_bundle.status == "VALID"
    assert saved_bundle.bundle_id == "bundle-store-001"

    # 3. Retrieve by bundle_id
    by_id = await bundle_repo.get_by_bundle_id("bundle-store-001")
    assert by_id is not None
    assert by_id.bundle_json["id"] == "bundle-store-001"

    # 4. Retrieve by patient_id
    by_pat = await bundle_repo.get_by_patient_id("pat-store-001", latest_only=True)
    assert len(by_pat) == 1
    assert by_pat[0].patient_mrn == "MRN-STORE-001"

    # 5. Retrieve by MRN
    by_mrn = await bundle_repo.get_by_patient_mrn("MRN-STORE-001", latest_only=True)
    assert len(by_mrn) == 1
    assert by_mrn[0].id == saved_bundle.id


@pytest.mark.asyncio
async def test_fhir_bundle_repository_idempotency_and_versioning(db_session: AsyncSession):
    """Verify duplicate content returns existing bundle (idempotency) and new content creates version 2."""
    pat_repo = PatientRepository(db_session)
    bundle_repo = FHIRBundleRepository(db_session)

    patient = PatientModel(
        id="pat-version-002",
        source_system="hospital_a",
        mrn="MRN-VER-002",
        first_name="Clara",
        last_name="Oswald",
        administrative_gender="female",
    )
    await pat_repo.create_patient(patient, [])

    bundle_v1 = {
        "resourceType": "Bundle",
        "id": "bundle-ver-002",
        "type": "collection",
        "entry": [{"resource": {"resourceType": "Patient", "id": "pat-version-002"}}],
    }

    # First save -> version 1
    b1, is_new1 = await bundle_repo.save_bundle(
        bundle_id="bundle-ver-002-v1",
        patient_id="pat-version-002",
        patient_mrn="MRN-VER-002",
        bundle_type="collection",
        bundle_json=bundle_v1,
    )
    await db_session.commit()
    assert is_new1 is True
    assert b1.version == 1

    # Idempotent re-save of exact same bundle content -> returns existing without duplicate
    b1_repeat, is_new_repeat = await bundle_repo.save_bundle(
        bundle_id="bundle-ver-002-v1",
        patient_id="pat-version-002",
        patient_mrn="MRN-VER-002",
        bundle_type="collection",
        bundle_json=bundle_v1,
    )
    assert is_new_repeat is False
    assert b1_repeat.id == b1.id
    assert b1_repeat.version == 1

    # Modified content -> auto-increments version to 2
    bundle_v2 = dict(bundle_v1)
    bundle_v2["entry"] = [
        {"resource": {"resourceType": "Patient", "id": "pat-version-002"}},
        {"resource": {"resourceType": "DocumentReference", "id": "doc-new", "status": "current"}},
    ]

    b2, is_new2 = await bundle_repo.save_bundle(
        bundle_id="bundle-ver-002-v2",
        patient_id="pat-version-002",
        patient_mrn="MRN-VER-002",
        bundle_type="collection",
        bundle_json=bundle_v2,
    )
    await db_session.commit()
    assert is_new2 is True
    assert b2.version == 2


def test_file_storage_atomic_write_and_permissions(tmp_path):
    """Verify FHIRBundleFileStorage writes atomically with 0o600 file and 0o700 dir permissions."""
    storage = FHIRBundleFileStorage(base_dir=str(tmp_path / "bundles"))

    bundle_data = {
        "resourceType": "Bundle",
        "id": "b-atomic-1",
        "type": "collection",
        "entry": [],
    }

    file_path = storage.save_bundle(
        patient_id="pat-atomic-1",
        bundle_id="b-atomic-1",
        bundle_data=bundle_data,
        version=1,
    )

    path_obj = Path(file_path)
    assert path_obj.exists()

    # Check directory permissions (0o700)
    parent_mode = path_obj.parent.stat().st_mode & 0o777
    assert parent_mode == 0o700, f"Expected 0o700 dir permissions, got {oct(parent_mode)}"

    # Check file permissions (0o600)
    file_mode = path_obj.stat().st_mode & 0o777
    assert file_mode == 0o600, f"Expected 0o600 file permissions, got {oct(file_mode)}"

    # Check deserialization roundtrip
    loaded = storage.load_bundle(file_path)
    assert loaded["id"] == "b-atomic-1"
    assert loaded["resourceType"] == "Bundle"


def test_file_storage_missing_file_raises_storage_exception(tmp_path):
    """Verify loading non-existent file cleanly raises StorageException."""
    storage = FHIRBundleFileStorage(base_dir=str(tmp_path))
    with pytest.raises(StorageException):
        storage.load_bundle(str(tmp_path / "non_existent.json"))


def test_file_storage_path_traversal_protection(tmp_path):
    """Verify path traversal attempts are rejected with StorageException."""
    storage = FHIRBundleFileStorage(base_dir=str(tmp_path / "bundles"))

    # Illegal patient_id
    with pytest.raises(StorageException):
        storage.save_bundle(patient_id="../../etc", bundle_id="b1", bundle_data={}, version=1)

    # Illegal bundle_id
    with pytest.raises(StorageException):
        storage.save_bundle(patient_id="p1", bundle_id="../traversal", bundle_data={}, version=1)

    # Illegal load_bundle outside base_dir
    with pytest.raises(StorageException):
        storage.load_bundle("/etc/passwd")


def test_compute_bundle_hash_strips_dynamic_envelope():
    """Verify compute_bundle_hash produces identical hashes regardless of dynamic id/timestamp."""
    bundle_a = {
        "resourceType": "Bundle",
        "id": "bundle-dynamic-111",
        "timestamp": "2026-11-20T10:00:00Z",
        "type": "collection",
        "entry": [{"resource": {"resourceType": "Patient", "id": "p1"}}],
    }
    bundle_b = {
        "resourceType": "Bundle",
        "id": "bundle-dynamic-999-DIFFERENT",
        "timestamp": "2026-11-21T18:00:00Z",
        "type": "collection",
        "entry": [{"resource": {"resourceType": "Patient", "id": "p1"}}],
    }

    hash_a = compute_bundle_hash(bundle_a)
    hash_b = compute_bundle_hash(bundle_b)
    assert hash_a == hash_b, "Content hash must be deterministic across dynamic envelope tokens!"
