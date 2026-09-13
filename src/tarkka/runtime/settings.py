"""Centralized environment-derived settings shared by CLI composition roots.

`tarkka.interfaces.main` and `tarkka.interfaces.cli` each defined their own byte-identical
``_home()`` reading ``TARKKA_HOME``, and each independently implemented the same
strip/lowercase/default-to-"json"/reject-anything-else parsing shape for a backend-selection
environment variable (``TARKKA_DOCUMENT_BACKEND`` and ``TARKKA_WORK_BACKEND`` respectively, with
different error text naming their own variable). This module is the single place that logic lives.

Scope is deliberately narrow: this only resolves and validates environment values. It does not
construct repositories, services, or a full dependency-injection container -- see the tracked
follow-up issue for that larger `TarkkaRuntime` composition-root work. ``home`` and each backend
are resolved independently (not as one eagerly-validated bundle) so that, exactly as before the
refactor, an invalid ``TARKKA_WORK_BACKEND`` never raises for a code path that only cares about
``TARKKA_DOCUMENT_BACKEND`` (or vice versa) -- collapsing that into one eagerly-validated object
would be a real, if narrow, behavior change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_SUPPORTED_BACKENDS = frozenset({"json", "postgres"})


def _parse_backend(env_var: str, raw: str) -> str:
    backend = raw.strip().lower() or "json"
    if backend in _SUPPORTED_BACKENDS:
        return backend
    raise ValueError(
        f"unsupported {env_var} {raw!r}; supported values are 'json' and 'postgres'"
    )


def resolve_document_backend() -> str:
    """Return the validated ``TARKKA_DOCUMENT_BACKEND`` value, defaulting to ``"json"``."""
    return _parse_backend("TARKKA_DOCUMENT_BACKEND", os.environ.get("TARKKA_DOCUMENT_BACKEND", ""))


def resolve_work_backend() -> str:
    """Return the validated ``TARKKA_WORK_BACKEND`` value, defaulting to ``"json"``."""
    return _parse_backend("TARKKA_WORK_BACKEND", os.environ.get("TARKKA_WORK_BACKEND", ""))


@dataclass(frozen=True, slots=True)
class TarkkaSettings:
    """The local state directory, re-resolved fresh on every ``from_environment()`` call.

    Callers that also need a validated backend selection should call
    ``resolve_document_backend()``/``resolve_work_backend()`` directly rather than through this
    dataclass, since those two variables are independent of ``home`` and of each other.
    """

    home: Path

    @classmethod
    def from_environment(cls) -> TarkkaSettings:
        return cls(home=Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve())
