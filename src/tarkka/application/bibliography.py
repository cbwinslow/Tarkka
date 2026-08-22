from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tarkka.application.identity import CanonicalIdentityResolver
from tarkka.application.works import WorkCatalogService
from tarkka.domain.bibliography import BibliographyRecord
from tarkka.domain.models import Work
from tarkka.infrastructure.bibliography_interchange import parse_bibliography


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
        discovery_records = tuple(
            record.to_discovery_record(source_sha256) for record in records
        )
        candidates = self._identity.resolve(discovery_records)
        works = tuple(self._catalog.persist_candidate(candidate) for candidate in candidates)
        return BibliographyImportResult(
            source_path=source,
            source_sha256=source_sha256,
            records=records,
            works=works,
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
