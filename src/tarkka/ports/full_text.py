from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord


@dataclass(frozen=True, slots=True)
class FullTextResource:
    """One provider-resolved downloadable representation of a canonical Work."""

    provider: str
    source_uri: str
    media_type: str
    filename: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("full-text provider must not be blank")
        if not self.source_uri.strip():
            raise ValueError("full-text source URI must not be blank")
        if not self.media_type.strip():
            raise ValueError("full-text media type must not be blank")
        if not self.filename.strip():
            raise ValueError("full-text filename must not be blank")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class FullTextResolver(Protocol):
    name: str

    def resolve(
        self,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> FullTextResource | None: ...


class BinaryFetcher(Protocol):
    def fetch(self, resource: FullTextResource, destination: str) -> None: ...
