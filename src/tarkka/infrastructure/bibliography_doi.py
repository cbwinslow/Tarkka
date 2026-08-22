from __future__ import annotations

from urllib.parse import unquote, urlsplit

from tarkka.domain.identifiers import try_normalize_doi
from tarkka.infrastructure.bibliography_errors import BibliographyParseError

_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org"})
_TRAILING_CITATION_PUNCTUATION = ".,;:"


def normalize_doi_identity(
    *,
    label: str,
    explicit_doi: str | None,
    url: str | None,
) -> str | None:
    """Reconcile explicit and doi.org URL observations without silently choosing conflicts."""
    normalized_explicit = try_normalize_doi(explicit_doi)
    url_doi = doi_from_url(url)
    if normalized_explicit and url_doi and normalized_explicit != url_doi:
        raise BibliographyParseError(f"{label} has conflicting DOI and DOI URL")
    return normalized_explicit or url_doi


def doi_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host not in _DOI_HOSTS:
        return None
    candidate = unquote(parts.path.lstrip("/")).rstrip(_TRAILING_CITATION_PUNCTUATION)
    return try_normalize_doi(candidate)
