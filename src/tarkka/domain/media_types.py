from __future__ import annotations

import re
from typing import overload

_TOKEN_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


@overload
def normalize_media_type(value: None) -> None: ...


@overload
def normalize_media_type(value: str) -> str: ...


def normalize_media_type(value: str | None) -> str | None:
    """Normalize an HTTP media type to lowercase type/subtype without parameters."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("media type must be a non-blank string when provided")
    normalized = value.split(";", 1)[0].strip().lower()
    if normalized.count("/") != 1:
        raise ValueError("media type must contain exactly one type/subtype separator")
    major, minor = normalized.split("/", 1)
    if _TOKEN_RE.fullmatch(major) is None or _TOKEN_RE.fullmatch(minor) is None:
        raise ValueError("media type must be a valid type/subtype value")
    return normalized
