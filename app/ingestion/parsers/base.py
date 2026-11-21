"""Base parser interface for multi-format EHR data ingestion."""

from abc import ABC, abstractmethod
from typing import BinaryIO, Iterator, Optional, TextIO, Union

from app.schemas.canonical import MappingProfile, RawRecord


class BaseParser(ABC):
    """Abstract interface implemented by all EHR input format parsers."""

    @abstractmethod
    def parse(
        self,
        stream_or_data: Union[str, bytes, TextIO, BinaryIO],
        source_system: str = "generic_ehr",
        mapping_profile: Optional[MappingProfile] = None,
    ) -> Iterator[RawRecord]:
        """Parse raw stream or data into an iterator of standardized RawRecord objects."""
        pass
