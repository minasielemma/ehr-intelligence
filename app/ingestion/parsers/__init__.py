"""Multi-format EHR input parsers and registry."""

from typing import Dict, Type
from app.core.exceptions import ValidationException
from app.ingestion.parsers.base import BaseParser
from app.ingestion.parsers.csv_parser import CSVParser
from app.ingestion.parsers.fhir_parser import FHIRParser
from app.ingestion.parsers.json_parser import JSONParser
from app.ingestion.parsers.package_processor import ExtractedPackageFile, PackageManifest, PackageProcessor
from app.ingestion.parsers.text_parser import TextParser

_PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {
    "json": JSONParser,
    "csv": CSVParser,
    "text": TextParser,
    "txt": TextParser,
    "plain": TextParser,
    "fhir": FHIRParser,
    "ndjson": FHIRParser,
    "jsonl": FHIRParser,
    "bundle": FHIRParser,
    "fhir_r4": FHIRParser,
}


def get_parser_for_format(format_name: str) -> BaseParser:
    """Instantiate appropriate parser for specified format or raise ValidationException."""
    normalized = format_name.lower().strip().lstrip(".")
    parser_cls = _PARSER_REGISTRY.get(normalized)
    if not parser_cls:
        raise ValidationException(
            message=f"Unsupported ingestion format: '{format_name}'",
            details={"supported_formats": list(_PARSER_REGISTRY.keys())},
        )
    return parser_cls()


__all__ = [
    "BaseParser",
    "CSVParser",
    "FHIRParser",
    "JSONParser",
    "PackageProcessor",
    "PackageManifest",
    "ExtractedPackageFile",
    "TextParser",
    "get_parser_for_format",
]
