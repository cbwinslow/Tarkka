from __future__ import annotations

import re
from typing import Any

_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.IGNORECASE)
_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")


def normalize_doi(value: str) -> str:
    """Return a canonical DOI string without resolver/scheme prefixes.

    Raises:
        ValueError: If the DOI is blank or does not match accepted DOI syntax.
    """
    doi = value.strip().lower()
    while True:
        for prefix in _PREFIXES:
            if doi.startswith(prefix):
                doi = doi.removeprefix(prefix).strip()
                break
        else:
            break
    if not doi:
        raise ValueError("DOI must not be blank")
    if not _DOI_RE.fullmatch(doi):
        raise ValueError(f"invalid DOI: {value!r}")
    return doi


def try_normalize_doi(value: Any) -> str | None:
    """Normalize an untrusted DOI-like value, returning ``None`` when invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_doi(value)
    except ValueError:
        return None
