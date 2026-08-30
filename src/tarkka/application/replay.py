"""Transport-neutral contracts for deterministic normalized-Document replay."""

from __future__ import annotations

import json
import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from tarkka import __version__
from tarkka.ports.parsing import DocumentParser

DEFAULT_REPLAY_MISMATCH_LIMIT = 20
DEFAULT_REPLAY_DIAGNOSTIC_CHARS = 160


class ReplayDeterminism(StrEnum):
    """How strongly Tarkka can characterize a parser replay."""

    DETERMINISTIC = "deterministic"
    ENVIRONMENT_SENSITIVE = "environment_sensitive"


class ReplayStatus(StrEnum):
    """Outcome of an executed replay comparison."""

    MATCHED = "matched"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class ReplayParserRegistration:
    """One exact executable parser identity and its reproducibility classification."""

    parser: DocumentParser
    determinism: ReplayDeterminism
    dependency_name: str | None = None
    dependency_version: str | None = None

    def __post_init__(self) -> None:
        if not self.parser.name.strip() or not self.parser.version.strip():
            raise ValueError("replay parser name/version must not be blank")
        if self.dependency_name is not None and not self.dependency_name.strip():
            raise ValueError("replay dependency name must not be blank")
        if self.dependency_version is not None and not self.dependency_version.strip():
            raise ValueError("replay dependency version must not be blank")
        if self.dependency_version is not None and self.dependency_name is None:
            raise ValueError("replay dependency version requires a dependency name")

    @property
    def identity(self) -> tuple[str, str]:
        return (self.parser.name, self.parser.version)


class ReplayParserRegistry:
    """Resolve replay parsers by exact persisted semantic identity only."""

    def __init__(self, registrations: Sequence[ReplayParserRegistration]) -> None:
        by_identity: dict[tuple[str, str], ReplayParserRegistration] = {}
        for registration in registrations:
            if registration.identity in by_identity:
                name, version = registration.identity
                raise ValueError(f"duplicate replay parser identity: {name}/{version}")
            by_identity[registration.identity] = registration
        self._by_identity = by_identity

    def resolve(self, parser_name: str, parser_version: str) -> ReplayParserRegistration | None:
        """Return only the exact registered parser identity; never substitute another version."""
        return self._by_identity.get((parser_name, parser_version))


@dataclass(frozen=True, slots=True)
class ReplayImplementation:
    """Execution identity kept separate from deterministic Document content equality."""

    parser_name: str
    parser_version: str
    tarkka_version: str
    python_implementation: str
    python_version: str
    dependency_name: str | None = None
    dependency_version: str | None = None

    @classmethod
    def from_registration(cls, registration: ReplayParserRegistration) -> ReplayImplementation:
        return cls(
            parser_name=registration.parser.name,
            parser_version=registration.parser.version,
            tarkka_version=__version__,
            python_implementation=platform.python_implementation(),
            python_version=platform.python_version(),
            dependency_name=registration.dependency_name,
            dependency_version=registration.dependency_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "tarkka_version": self.tarkka_version,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "dependency_name": self.dependency_name,
            "dependency_version": self.dependency_version,
        }


@dataclass(frozen=True, slots=True)
class ReplayMismatch:
    """One bounded structural/content difference between expected and replayed Documents."""

    path: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "expected": self.expected, "actual": self.actual}


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Machine-readable result suitable for CLI now and MCP/HTTP later."""

    status: ReplayStatus
    bundle_sha256: str
    document_id: str
    expected_sha256: str
    actual_sha256: str
    determinism: ReplayDeterminism
    implementation: ReplayImplementation
    mismatches: tuple[ReplayMismatch, ...] = ()

    @property
    def matched(self) -> bool:
        return self.status is ReplayStatus.MATCHED

    def to_dict(self) -> dict[str, object]:
        return {
            "matched": self.matched,
            "status": self.status.value,
            "bundle_sha256": self.bundle_sha256,
            "document_id": self.document_id,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "determinism": self.determinism.value,
            "implementation": self.implementation.to_dict(),
            "mismatches": [item.to_dict() for item in self.mismatches],
        }


def replay_mismatches(
    expected: object,
    actual: object,
    *,
    limit: int = DEFAULT_REPLAY_MISMATCH_LIMIT,
    diagnostic_chars: int = DEFAULT_REPLAY_DIAGNOSTIC_CHARS,
) -> tuple[ReplayMismatch, ...]:
    """Return a deterministic bounded structural diff without dumping large source content."""
    if limit < 1:
        raise ValueError("replay mismatch limit must be positive")
    if diagnostic_chars < 1:
        raise ValueError("replay diagnostic character limit must be positive")

    mismatches: list[ReplayMismatch] = []

    def add(path: str, expected_value: object, actual_value: object) -> None:
        # Every call site checks the limit before invoking add. Keeping the guard here as well
        # created an unreachable false branch that could only be covered by bypassing walk().
        mismatches.append(
            ReplayMismatch(
                path=path or "$",
                expected=_diagnostic(expected_value, diagnostic_chars),
                actual=_diagnostic(actual_value, diagnostic_chars),
            )
        )

    def walk(path: str, expected_value: object, actual_value: object) -> None:
        if isinstance(expected_value, Mapping) and isinstance(actual_value, Mapping):
            expected_keys = {str(key) for key in expected_value}
            actual_keys = {str(key) for key in actual_value}
            for key in sorted(expected_keys | actual_keys):
                child_path = f"{path}.{key}" if path else key
                if key not in expected_value:
                    add(child_path, "<missing>", actual_value[key])
                elif key not in actual_value:
                    add(child_path, expected_value[key], "<missing>")
                else:
                    walk(child_path, expected_value[key], actual_value[key])
                if len(mismatches) >= limit:
                    return
            return
        if isinstance(expected_value, list) and isinstance(actual_value, list):
            if len(expected_value) != len(actual_value):
                add(f"{path}.length" if path else "length", len(expected_value), len(actual_value))
                if len(mismatches) >= limit:
                    return
            for index, (expected_item, actual_item) in enumerate(
                zip(expected_value, actual_value, strict=False)
            ):
                walk(f"{path}[{index}]", expected_item, actual_item)
                if len(mismatches) >= limit:
                    return
            return
        if expected_value != actual_value:
            add(path, expected_value, actual_value)

    walk("", expected, actual)
    return tuple(mismatches)


def _diagnostic(value: object, maximum_chars: int) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        rendered = repr(value)
    if len(rendered) <= maximum_chars:
        return rendered
    return rendered[: maximum_chars - 1] + "…"
