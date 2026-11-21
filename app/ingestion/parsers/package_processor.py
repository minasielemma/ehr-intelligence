"""Package processor for extracting, validating, and sequencing hospital EHR export archives.

Provides robust protection against:
- ZipSlip / Directory Traversal attacks.
- Decompression bombs (size and compression ratio limits).
- Corrupted archives via SHA-256 checksum verification against manifests.
- Dependency inversion via topological ordering of domain files.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union
import zipfile

from app.core.config import get_settings
from app.core.exceptions import ValidationException
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

DOMAIN_INGESTION_RANK = {
    "organizations": 1,
    "facilities": 1,
    "practitioners": 2,
    "providers": 2,
    "patients": 3,
    "demographics": 3,
    "coverages": 4,
    "insurance": 4,
    "encounters": 5,
    "visits": 5,
    "admissions": 5,
    "care_plans": 6,
    "consents": 6,
    "service_requests": 6,
    "conditions": 7,
    "diagnoses": 7,
    "observations": 7,
    "vitals": 7,
    "labs": 7,
    "medication_requests": 7,
    "medications": 7,
    "procedures": 7,
    "allergies": 7,
    "immunizations": 7,
    "medication_administrations": 8,
    "diagnostic_reports": 8,
    "imaging_studies": 8,
    "claims": 8,
    "documents": 8,
    "notes": 8,
    "clinical_notes": 8,
    "provenances": 9,
    "fhir": 10,
    "consolidated": 11,
    "other": 99,
}


@dataclass
class ExtractedPackageFile:
    """Represents a validated file ready for domain-specific ingestion."""
    filename: str
    absolute_path: Path
    relative_path: str
    file_size: int
    sha256_hash: str
    detected_format: str
    domain: str
    sort_rank: int


@dataclass
class PackageManifest:
    """Parsed metadata from dataset manifest.json and data_dictionary.json."""
    dataset_name: Optional[str] = None
    export_timestamp: Optional[str] = None
    hospital_name: Optional[str] = None
    source_system: str = "hospital_ehr"
    total_files: int = 0
    declared_checksums: Dict[str, str] = field(default_factory=dict)
    file_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    data_dictionary: Dict[str, Any] = field(default_factory=dict)
    raw_manifest: Dict[str, Any] = field(default_factory=dict)


class PackageProcessor:
    """Handles secure extraction, integrity validation, and ordering of EHR export packages."""

    @classmethod
    def compute_sha256(cls, file_path: Path) -> str:
        """Compute SHA-256 hexadecimal digest for a file on disk."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest().lower()

    @classmethod
    def detect_domain(cls, file_name: str, declared_domain: Optional[str] = None) -> Tuple[str, int]:
        """Detect healthcare domain and ordering rank from filename or manifest declaration."""
        if declared_domain:
            norm_dec = declared_domain.lower().strip()
            rank = DOMAIN_INGESTION_RANK.get(norm_dec, 99)
            return norm_dec, rank

        name_lower = Path(file_name).stem.lower().replace("-", "_").replace(" ", "_")

        for domain_key, rank in DOMAIN_INGESTION_RANK.items():
            if domain_key in name_lower:
                return domain_key, rank

        if "patient" in name_lower:
            return "patients", DOMAIN_INGESTION_RANK["patients"]
        if "encounter" in name_lower or "visit" in name_lower:
            return "encounters", DOMAIN_INGESTION_RANK["encounters"]
        if "cond" in name_lower or "diag" in name_lower:
            return "conditions", DOMAIN_INGESTION_RANK["conditions"]
        if "obs" in name_lower or "vital" in name_lower or "lab" in name_lower:
            return "observations", DOMAIN_INGESTION_RANK["observations"]
        if "med" in name_lower:
            return "medication_requests", DOMAIN_INGESTION_RANK["medication_requests"]
        if "proc" in name_lower or "surg" in name_lower:
            return "procedures", DOMAIN_INGESTION_RANK["procedures"]
        if "note" in name_lower or "doc" in name_lower or "summary" in name_lower:
            return "documents", DOMAIN_INGESTION_RANK["documents"]
        if "claim" in name_lower or "bill" in name_lower:
            return "claims", DOMAIN_INGESTION_RANK["claims"]
        if "cover" in name_lower or "insur" in name_lower:
            return "coverages", DOMAIN_INGESTION_RANK["coverages"]
        if "allergy" in name_lower or "allerg" in name_lower:
            return "allergies", DOMAIN_INGESTION_RANK["allergies"]
        if "immun" in name_lower or "vacc" in name_lower:
            return "immunizations", DOMAIN_INGESTION_RANK["immunizations"]
        if "org" in name_lower or "facil" in name_lower:
            return "organizations", DOMAIN_INGESTION_RANK["organizations"]
        if "pract" in name_lower or "doc" in name_lower or "prov" in name_lower:
            return "practitioners", DOMAIN_INGESTION_RANK["practitioners"]
        if "fhir" in name_lower or "bundle" in name_lower:
            return "fhir", DOMAIN_INGESTION_RANK["fhir"]

        return "other", 99

    @classmethod
    def detect_format(cls, file_name: str) -> str:
        """Infer file format based on extension."""
        suffix = Path(file_name).suffix.lower()
        if suffix in [".csv"]:
            return "csv"
        elif suffix in [".ndjson", ".jsonl"]:
            return "ndjson"
        elif suffix in [".json"]:
            return "json"
        elif suffix in [".txt", ".text"]:
            return "text"
        return "binary"

    @classmethod
    def extract_and_validate(
        cls,
        archive_path_or_bytes: Union[str, Path, bytes, BinaryIO],
        destination_dir: Path,
    ) -> Tuple[PackageManifest, List[ExtractedPackageFile]]:
        """Safely extract archive, enforce security limits, verify checksums, and order files."""
        destination_dir = destination_dir.resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)

        archive_file: Optional[Path] = None
        temp_archive_created = False

        if isinstance(archive_path_or_bytes, (str, Path)):
            archive_file = Path(archive_path_or_bytes).resolve()
        elif isinstance(archive_path_or_bytes, bytes):
            archive_file = destination_dir / "_temp_upload_archive.pkg"
            archive_file.write_bytes(archive_path_or_bytes)
            temp_archive_created = True
        elif hasattr(archive_path_or_bytes, "read"):
            archive_file = destination_dir / "_temp_upload_archive.pkg"
            with open(archive_file, "wb") as f:
                shutil.copyfileobj(archive_path_or_bytes, f)
            temp_archive_created = True

        if not archive_file or not archive_file.exists():
            raise ValidationException("Failed to locate or stage archive package for extraction")

        try:
            is_zip = zipfile.is_zipfile(archive_file)
            is_tar = tarfile.is_tarfile(archive_file)

            if not is_zip and not is_tar:
                raise ValidationException(
                    "Unsupported archive format. Expected valid ZIP, TAR, or TGZ package."
                )

            if is_zip:
                cls._extract_zip(archive_file, destination_dir)
            else:
                cls._extract_tar(archive_file, destination_dir)
        finally:
            if temp_archive_created and archive_file and archive_file.exists():
                try:
                    archive_file.unlink()
                except Exception:
                    pass
        manifest = cls._parse_manifest_and_metadata(destination_dir)
        extracted_files: List[ExtractedPackageFile] = []
        for file_path in destination_dir.rglob("*"):
            if not file_path.is_file():
                continue

            rel_str = str(file_path.relative_to(destination_dir)).replace("\\", "/")
            base_name = file_path.name.lower()
            if base_name in ["manifest.json", "checksums.sha256", "data_dictionary.json", "data_dictionary.csv", ".ds_store"]:
                continue
            actual_sha = cls.compute_sha256(file_path)
            expected_sha = manifest.declared_checksums.get(rel_str) or manifest.declared_checksums.get(file_path.name)
            if expected_sha and actual_sha != expected_sha.lower():
                raise ValidationException(
                    f"Integrity check failed: Checksum mismatch for '{rel_str}'. "
                    f"Expected {expected_sha}, calculated {actual_sha}."
                )

            file_meta = manifest.file_metadata.get(rel_str) or manifest.file_metadata.get(file_path.name, {})
            declared_domain = file_meta.get("domain")

            domain, rank = cls.detect_domain(file_path.name, declared_domain)
            fmt = file_meta.get("format") or cls.detect_format(file_path.name)

            extracted_files.append(
                ExtractedPackageFile(
                    filename=file_path.name,
                    absolute_path=file_path,
                    relative_path=rel_str,
                    file_size=file_path.stat().st_size,
                    sha256_hash=actual_sha,
                    detected_format=fmt,
                    domain=domain,
                    sort_rank=rank,
                )
            )
        extracted_files.sort(key=lambda x: (x.sort_rank, x.relative_path))
        manifest.total_files = len(extracted_files)

        return manifest, extracted_files

    @classmethod
    def _extract_zip(cls, archive_file: Path, destination_dir: Path) -> None:
        """Securely extract ZIP archive enforcing path traversal and size limits."""
        dest_resolved = destination_dir.resolve()
        compressed_size = archive_file.stat().st_size

        with zipfile.ZipFile(archive_file, "r") as zf:
            total_uncompressed_size = 0
            infolist = zf.infolist()

            for info in infolist:
                target_path = (dest_resolved / info.filename).resolve()
                if not str(target_path).startswith(str(dest_resolved)):
                    raise ValidationException(
                        f"ZipSlip security violation: path traversal detected in '{info.filename}'"
                    )

                total_uncompressed_size += info.file_size
            if total_uncompressed_size > settings.MAX_DECOMPRESSED_SIZE_BYTES:
                raise ValidationException(
                    f"Decompression bomb rejected: uncompressed package size {total_uncompressed_size} bytes "
                    f"exceeds safety threshold ({settings.MAX_DECOMPRESSED_SIZE_BYTES} bytes)"
                )

            compression_ratio = total_uncompressed_size / max(compressed_size, 1)
            if compression_ratio > settings.MAX_DECOMPRESSION_RATIO:
                raise ValidationException(
                    f"Decompression bomb rejected: compression ratio {compression_ratio:.2f} "
                    f"exceeds safety limit ({settings.MAX_DECOMPRESSION_RATIO})"
                )

            bytes_written = 0
            for info in infolist:
                if info.is_dir():
                    continue

                target_path = (dest_resolved / info.filename).resolve()
                if not str(target_path).startswith(str(dest_resolved)):
                    raise ValidationException(f"ZipSlip path traversal attempt: {info.filename}")

                target_path.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(info) as src, open(target_path, "wb") as dst:
                    while chunk := src.read(65536):
                        bytes_written += len(chunk)
                        if bytes_written > settings.MAX_DECOMPRESSED_SIZE_BYTES:
                            raise ValidationException(
                                "Decompression size exceeded maximum allowed limit during extraction"
                            )
                        dst.write(chunk)

    @classmethod
    def _extract_tar(cls, archive_file: Path, destination_dir: Path) -> None:
        """Securely extract TAR / TGZ archive enforcing path traversal and size limits."""
        dest_resolved = destination_dir.resolve()
        compressed_size = archive_file.stat().st_size

        with tarfile.open(archive_file, "r:*") as tf:
            total_uncompressed_size = 0
            members = tf.getmembers()

            for member in members:
                target_path = (dest_resolved / member.name).resolve()
                if not str(target_path).startswith(str(dest_resolved)):
                    raise ValidationException(
                        f"Path traversal violation in tar archive: '{member.name}'"
                    )
                total_uncompressed_size += member.size

            if total_uncompressed_size > settings.MAX_DECOMPRESSED_SIZE_BYTES:
                raise ValidationException(
                    f"Decompression bomb rejected: uncompressed size {total_uncompressed_size} bytes "
                    f"exceeds limit ({settings.MAX_DECOMPRESSED_SIZE_BYTES} bytes)"
                )

            compression_ratio = total_uncompressed_size / max(compressed_size, 1)
            if compression_ratio > settings.MAX_DECOMPRESSION_RATIO:
                raise ValidationException(
                    f"Decompression bomb rejected: compression ratio {compression_ratio:.2f} "
                    f"exceeds safety threshold ({settings.MAX_DECOMPRESSION_RATIO})"
                )
            bytes_written = 0
            for member in members:
                if not member.isfile():
                    continue

                target_path = (dest_resolved / member.name).resolve()
                if not str(target_path).startswith(str(dest_resolved)):
                    raise ValidationException(f"Path traversal attempt: {member.name}")

                target_path.parent.mkdir(parents=True, exist_ok=True)

                src = tf.extractfile(member)
                if src:
                    with open(target_path, "wb") as dst:
                        while chunk := src.read(65536):
                            bytes_written += len(chunk)
                            if bytes_written > settings.MAX_DECOMPRESSED_SIZE_BYTES:
                                raise ValidationException(
                                    "Decompression size exceeded limit during extraction"
                                )
                            dst.write(chunk)

    @classmethod
    def _parse_manifest_and_metadata(cls, destination_dir: Path) -> PackageManifest:
        """Parse manifest.json, checksums.sha256, and data_dictionary.json if available."""
        manifest = PackageManifest()

        manifest_file = destination_dir / "manifest.json"
        if manifest_file.exists():
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifest.raw_manifest = data
                manifest.dataset_name = data.get("dataset_name") or data.get("name")
                manifest.export_timestamp = data.get("export_timestamp") or data.get("timestamp")
                manifest.hospital_name = data.get("hospital_name") or data.get("provider")
                manifest.source_system = data.get("source_system") or "hospital_ehr"
                for f_entry in data.get("files", []):
                    if isinstance(f_entry, dict):
                        f_name = f_entry.get("filename") or f_entry.get("path")
                        if f_name:
                            manifest.file_metadata[f_name] = f_entry
                            if f_entry.get("sha256"):
                                manifest.declared_checksums[f_name] = f_entry["sha256"].lower()
            except Exception as exc:
                logger.warning("Failed to parse manifest.json: %s", exc)

        checksum_file = destination_dir / "checksums.sha256"
        if checksum_file.exists():
            try:
                for line in checksum_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        chk_hash = parts[0].strip().lower()
                        chk_file = parts[1].strip().lstrip("./*").replace("\\", "/")
                        manifest.declared_checksums[chk_file] = chk_hash
            except Exception as exc:
                logger.warning("Failed to parse checksums.sha256: %s", exc)
        data_dict_file = destination_dir / "data_dictionary.json"
        if data_dict_file.exists():
            try:
                manifest.data_dictionary = json.loads(data_dict_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to parse data_dictionary.json: %s", exc)

        return manifest
