"""Deterministic record fingerprinting and duplicate detection service."""

import hashlib
import json
from typing import Any, Dict, Optional, Tuple


class RecordFingerprinter:
    """Computes deterministic cryptographic fingerprints for EHR clinical records."""

    @classmethod
    def compute_content_hash(cls, content: Optional[str], payload: Optional[Dict[str, Any]] = None) -> str:
        """Compute SHA-256 digest of clinical content or structured payload."""
        hasher = hashlib.sha256()
        if content:
            hasher.update(content.strip().encode("utf-8"))
        if payload:
            try:
                serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                hasher.update(serialized.encode("utf-8"))
            except Exception:
                hasher.update(str(payload).encode("utf-8"))
        return hasher.hexdigest()

    @classmethod
    def generate_fingerprint(
        cls,
        source_system: str,
        patient_mrn: str,
        record_type: str,
        record_date: Optional[str],
        content_hash: str,
        source_record_id: Optional[str] = None,
    ) -> str:
        """Compute SHA-256 record fingerprint from core clinical provenance attributes."""
        components = [
            source_system.strip().lower(),
            patient_mrn.strip(),
            record_type.strip().lower(),
            (record_date or "NODATE").strip(),
            content_hash,
        ]
        if source_record_id:
            components.append(str(source_record_id).strip())

        token = "|".join(components)
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def classify_record_duplicate_or_update(
        cls,
        existing_fingerprint: Optional[str],
        incoming_fingerprint: str,
        existing_content_hash: Optional[str],
        incoming_content_hash: str,
    ) -> Tuple[str, str]:
        """Classify relation between existing and incoming record with identical identifiers.
        
        Returns:
            Tuple of (Classification: 'EXACT_DUPLICATE' | 'VALID_UPDATE' | 'CONTENT_CONFLICT', reason)
        """
        if existing_fingerprint == incoming_fingerprint:
            return "EXACT_DUPLICATE", "Exact matching record fingerprint detected. Processing skipped as idempotent duplicate."

        if existing_content_hash != incoming_content_hash:
            return "VALID_UPDATE", "Record with same identifier contains modified clinical content; processed as an updated record."

        return "CONTENT_CONFLICT", "Record contains discrepant metadata or conflicting values; preserved with discrepancy flag."
