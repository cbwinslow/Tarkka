from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tarkka.application.identity import CanonicalIdentityResolver
from tarkka.application.works import WorkCatalogService
from tarkka.domain.bibliography import BibliographyRecord
from tarkka.domain.models import Work
from tarkka.infrastructure.bibliography_interchange import (
    BibliographyParseError,
    parse_bibliography,
)


@dataclass(frozen=True, slots=True)
class BibliographyImportResult:
    source_path: Path
    source_sha256: str
    records: tuple[BibliographyRecord, ...]
    works: tuple[Work, ...]


class BibliographyImportService:
    """Import bibliography interchange records through canonical Work identity."""

    def __init__(self, catalog: WorkCatalogService) -> None:
        self._catalog = catalog
        self._identity = CanonicalIdentityResolver()

    def import_file(self, path: Path) -> BibliographyImportResult:
        source = path.expanduser().resolve()
        source_sha256 = _sha256_file(source)
        records = parse_bibliography(source)
        _ensure_unique_source_keys(records)
        discovery_records = tuple(
            record.to_discovery_record(source_sha256) for record in records
        )
        candidates = self._identity.resolve(discovery_records)
        works = self._catalog.persist_candidates(candidates)
        return BibliographyImportResult(
            source_path=source,
            source_sha256=source_sha256,
            records=records,
            works=works,
        )


def _ensure_unique_source_keys(records: tuple[BibliographyRecord, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (record.source_format.value, record.source_key)
        if key in seen:
            raise BibliographyParseError(
                "duplicate bibliography source key is ambiguous within one file: "
                f"{record.source_key!r}"
            )
        seen.add(key)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
