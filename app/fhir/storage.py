"""Secure atomic file-based persistence for HL7 FHIR R4 Bundles."""

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.exceptions import StorageException
from app.core.logging import get_logger

logger = get_logger(__name__)

SAFE_ID_REGEX = re.compile(r"^[A-Za-z0-9\-\._]{1,64}$")


class FHIRBundleFileStorage:
    """Manages secure, atomic local filesystem persistence of FHIR R4 Bundles."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        settings = get_settings()
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            storage_root = Path(settings.DATABASE_PATH).parent
            self.base_dir = (storage_root / "fhir_bundles").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_id(self, val: str, name: str = "identifier") -> str:
        """Validate identifier against path traversal attacks."""
        if not val or not SAFE_ID_REGEX.match(val) or ".." in val:
            raise StorageException(f"Invalid {name} '{val}': must be 1-64 alphanumeric/hyphen characters without path traversal")
        return val

    def _ensure_patient_dir(self, patient_id: str) -> Path:
        """Create secure directory for patient bundles with 0o700 permissions."""
        sanitized_pid = self._sanitize_id(patient_id, "patient_id")
        patient_dir = (self.base_dir / sanitized_pid).resolve()
        if not patient_dir.is_relative_to(self.base_dir):
            raise StorageException(f"Path traversal detected for patient ID '{patient_id}'")

        if not patient_dir.exists():
            patient_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(patient_dir, 0o700)
            except OSError:
                pass
        return patient_dir

    def save_bundle(
        self,
        patient_id: str,
        bundle_id: str,
        bundle_data: Dict[str, Any],
        version: int = 1,
    ) -> str:
        """Atomically persist a FHIR Bundle JSON payload to disk.

        Uses write-to-temp-and-replace to ensure crash-safe atomic writes,
        and enforces 0o600 file permissions for patient privacy.

        Returns:
            Absolute file path to the stored JSON file.
        """
        sanitized_bid = self._sanitize_id(bundle_id, "bundle_id")
        patient_dir = self._ensure_patient_dir(patient_id)
        filename = f"{sanitized_bid}_v{version}.json"
        target_path = (patient_dir / filename).resolve()
        if not target_path.is_relative_to(self.base_dir):
            raise StorageException(f"Path traversal detected for target file '{filename}'")

        temp_fd, temp_path_str = tempfile.mkstemp(
            prefix=f".tmp_{sanitized_bid}_",
            dir=str(patient_dir),
            text=True,
        )
        temp_path = Path(temp_path_str)

        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(bundle_data, f, indent=2, ensure_ascii=False)
            
            os.chmod(temp_path, 0o600)
            
            os.replace(temp_path, target_path)
            logger.info("Atomically saved FHIR Bundle [%s] at [%s]", bundle_id, target_path)
            return str(target_path)
        except Exception as exc:
            try:
                os.close(temp_fd)
            except OSError:
                pass
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error("Failed to persist FHIR Bundle [%s] to disk: %s", bundle_id, exc)
            raise StorageException(f"Failed to persist FHIR bundle file: {exc}")

    def load_bundle(self, file_path: str) -> Dict[str, Any]:
        """Read and deserialize a stored FHIR Bundle JSON file."""
        path = Path(file_path).resolve()
        if not path.is_relative_to(self.base_dir):
            raise StorageException(f"Access denied: path traversal detected for file '{file_path}'")
        if not path.exists():
            raise StorageException(f"FHIR bundle file not found: {file_path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to read FHIR Bundle file [%s]: %s", file_path, exc)
            raise StorageException(f"Corrupted or unreadable FHIR bundle file: {exc}")

    def delete_bundle(self, file_path: str) -> bool:
        """Securely remove a bundle file."""
        path = Path(file_path).resolve()
        if not path.is_relative_to(self.base_dir):
            raise StorageException(f"Access denied: path traversal detected for file '{file_path}'")
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError as exc:
                logger.warning("Failed to delete bundle file [%s]: %s", file_path, exc)
                return False
        return False
