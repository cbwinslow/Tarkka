from __future__ import annotations

from dataclasses import replace
from urllib.parse import unquote, urlsplit

from tarkka.domain.bibliography import BibliographyRecord
from tarkka.domain.identifiers import try_normalize_doi
from tarkka.infrastructure.bibliography_bibtex import parse_bibtex as _parse_bibtex
from tarkka.infrastructure.bibliography_errors import BibliographyParseError

_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org"})
_TRAILING_CITATION_PUNCTUATION = ".,;:"


def parse_bibtex(text: str) -> tuple[BibliographyRecord, ...]:
    """Parse BibTeX and reconcile explicit/URL DOI observations fail-closed."""
    records = _parse_bibtex(text)
    return tuple(_normalize_doi_identity(record) for record in records)


def _normalize_doi_identity(record: BibliographyRecord) -> BibliographyRecord:
    explicit_doi = try_normalize_doi(record.doi)
    url_doi = _doi_from_url(record.url)
    if explicit_doi and url_doi and explicit_doi != url_doi:
        raise BibliographyParseError(
            f"BibTeX entry {record.source_key!r} has conflicting DOI and DOI URL"
        )
    return replace(record, doi=explicit_doi or url_doi)


def _doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host not in _DOI_HOSTS:
        return None
    candidate = unquote(parts.path.lstrip("/")).rstrip(_TRAILING_CITATION_PUNCTUATION)
    return try_normalize_doi(candidate)
