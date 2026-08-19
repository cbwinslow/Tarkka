from __future__ import annotations

import re

_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    """Return a canonical DOI string without resolver/scheme prefixes.

    Raises:
        ValueError: If the value is blank or does not match DOI syntax.
    """
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi.removeprefix(prefix).strip()
            break
    if not doi:
        raise ValueError("DOI must not be blank")
    if not _DOI_RE.fullmatch(doi):
        raise ValueError(f"invalid DOI: {value!r}")
    return doi
