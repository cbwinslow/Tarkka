from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
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
        if not _is_safe_filename(self.filename):
            raise ValueError("full-text filename must be one safe path component")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def _is_safe_filename(filename: str) -> bool:
    """Reject absolute, traversal, POSIX, and Windows path spellings."""
    if filename in {".", ".."} or "\x00" in filename:
        return False
    return (
        PurePosixPath(filename).name == filename
        and PureWindowsPath(filename).name == filename
    )


class FullTextResolver(Protocol):
    name: str

    def resolve(
        self,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> FullTextResource | None: ...


class BinaryFetcher(Protocol):
    def fetch(self, resource: FullTextResource, destination: Path) -> None: ...
