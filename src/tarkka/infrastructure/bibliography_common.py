from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from tarkka.infrastructure.bibliography_errors import BibliographyParseError

_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def stable_key(prefix: str, ordinal: int, raw: Any) -> str:
    try:
        encoded = json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BibliographyParseError(
            "bibliography source data is not deterministically serializable"
        ) from exc
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"{prefix}:{ordinal}:{digest}"


def year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 9999 else None
    match = _YEAR.search(str(value))
    return int(match.group(1)) if match else None


def optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def required_text(value: Any, label: str) -> str:
    result = optional_text(value)
    if result is None:
        raise BibliographyParseError(f"{label} must not be blank")
    return result
