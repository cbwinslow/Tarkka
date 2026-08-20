from __future__ import annotations

import re
from typing import Any

_DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.IGNORECASE)
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")
_ARXIV_RE = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})$", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_ARXIV_PREFIXES = (
    "https://arxiv.org/abs/",
    "http://arxiv.org/abs/",
    "https://arxiv.org/pdf/",
    "http://arxiv.org/pdf/",
    "arxiv:",
)


def normalize_doi(value: str) -> str:
    """Return a canonical DOI string without resolver/scheme prefixes."""
    doi = value.strip().lower()
    while True:
        for prefix in _DOI_PREFIXES:
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


def normalize_arxiv_id(value: str) -> str:
    """Return a version-independent canonical arXiv identifier."""
    arxiv_id = value.strip()
    lowered = arxiv_id.lower()
    for prefix in _ARXIV_PREFIXES:
        if lowered.startswith(prefix):
            arxiv_id = arxiv_id[len(prefix) :].strip()
            break
    if arxiv_id.lower().endswith(".pdf"):
        arxiv_id = arxiv_id[:-4]
    arxiv_id = _ARXIV_VERSION_RE.sub("", arxiv_id)
    if not arxiv_id or not _ARXIV_RE.fullmatch(arxiv_id):
        raise ValueError(f"invalid arXiv identifier: {value!r}")
    return arxiv_id


def try_normalize_arxiv_id(value: Any) -> str | None:
    """Normalize an untrusted arXiv-like value, returning ``None`` when invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_arxiv_id(value)
    except ValueError:
        return None
