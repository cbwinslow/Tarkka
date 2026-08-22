from __future__ import annotations

from dataclasses import replace

from tarkka.domain.bibliography import BibliographyRecord
from tarkka.infrastructure.bibliography_bibtex import parse_bibtex as _parse_bibtex
from tarkka.infrastructure.bibliography_doi import normalize_doi_identity


def parse_bibtex(text: str) -> tuple[BibliographyRecord, ...]:
    """Parse BibTeX and reconcile explicit/URL DOI observations fail-closed."""
    return tuple(_normalize_record_doi(record) for record in _parse_bibtex(text))


def _normalize_record_doi(record: BibliographyRecord) -> BibliographyRecord:
    doi = normalize_doi_identity(
        label=f"BibTeX entry {record.source_key!r}",
        explicit_doi=record.doi,
        url=record.url,
    )
    return replace(record, doi=doi)
