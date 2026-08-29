"""Stable runtime configuration helpers shared across Tarkka interfaces."""

from __future__ import annotations

import os
from typing import Literal

DocumentBackend = Literal["json", "postgres"]


def document_backend() -> DocumentBackend:
    """Return the configured durable document backend, defaulting to local JSON."""
    raw_backend = os.environ.get("TARKKA_DOCUMENT_BACKEND", "")
    backend = raw_backend.strip().lower() or "json"
    if backend == "json":
        return "json"
    if backend == "postgres":
        return "postgres"
    raise ValueError(
        "unsupported TARKKA_DOCUMENT_BACKEND "
        f"{raw_backend!r}; supported values are 'json' and 'postgres'"
    )
