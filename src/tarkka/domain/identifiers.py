from __future__ import annotations


def normalize_doi(value: str) -> str:
    """Return a canonical DOI string without resolver/scheme prefixes."""
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi.removeprefix(prefix).strip()
            break
    if not doi:
        raise ValueError("DOI must not be blank")
    return doi
