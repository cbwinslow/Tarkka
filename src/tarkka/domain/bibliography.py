from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.identifiers import try_normalize_doi


class BibliographyFormat(StrEnum):
    BIBTEX = "bibtex"
    RIS = "ris"
    CSL_JSON = "csl-json"


@dataclass(frozen=True, slots=True)
class BibliographyRecord:
    """One source-native bibliography entry before canonical Work resolution."""

    source_format: BibliographyFormat
    source_key: str
    entry_type: str
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValueError("bibliography source key must not be blank")
        if not self.entry_type.strip():
            raise ValueError("bibliography entry type must not be blank")
        if not self.title.strip():
            raise ValueError("bibliography title must not be blank")
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def to_discovery_record(self) -> DiscoveryRecord:
        normalized_doi = try_normalize_doi(self.doi)
        external_ids: dict[str, str] = {}
        if normalized_doi:
            external_ids["doi"] = normalized_doi
        metadata: dict[str, Any] = {
            "source_format": self.source_format.value,
            "entry_type": self.entry_type,
            "authors": self.authors,
            "native_fields": dict(self.fields),
        }
        return DiscoveryRecord(
            provider=f"bibliography:{self.source_format.value}",
            provider_id=self.source_key,
            title=self.title,
            year=self.year,
            doi=normalized_doi,
            landing_page_url=self.url,
            external_ids=external_ids,
            metadata=metadata,
        )
