"""Compact, transport-neutral discovery for Tarkka research services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResearchOperation:
    """One stable operation handle returned before its detailed schema is requested."""

    operation_id: str
    family: str
    summary: str
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ResearchCapabilities:
    """Small capability index suitable for first-turn agent routing."""

    version: str
    operations: tuple[ResearchOperation, ...]

    @property
    def estimated_tokens(self) -> int:
        return 80 + sum(item.estimated_tokens for item in self.operations)


_OPERATIONS = (
    ResearchOperation("research.discover", "discover", "Find provider-backed candidates.", 24),
    ResearchOperation("research.get", "get", "Resolve one stable research handle.", 24),
    ResearchOperation("research.expand", "expand", "Request a named deeper representation.", 24),
    ResearchOperation("research.verify", "verify", "Record or inspect evidence assessments.", 24),
)


def research_capabilities() -> ResearchCapabilities:
    """Return the intentionally compact first step of progressive tool discovery."""
    return ResearchCapabilities(version="1", operations=_OPERATIONS)
