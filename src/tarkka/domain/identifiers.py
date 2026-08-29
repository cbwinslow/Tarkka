from __future__ import annotations

import re
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def require_sha256(value: object, *, field_name: str = "SHA-256") -> str:
    """Return a canonical lowercase SHA-256 digest or fail closed."""
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be lowercase hexadecimal")
    return value


def artifact_id_from_sha256(sha256: str) -> UUID:
    """Return Tarkka's canonical stable Artifact UUID for one SHA-256 digest."""
    digest = require_sha256(sha256, field_name="artifact SHA-256")
    return uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")


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
    if arxiv_id.endswith(".pdf"):
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
