"""Compact, transport-neutral discovery for Tarkka research services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tarkka.application.discover import DiscoveryService
from tarkka.application.verification import EvidenceVerificationService

# Envelope metadata (version, representation, and routing hints) is included
# alongside every capability response. Keeping it separate from per-operation
# estimates makes the deliberately approximate number auditable.
_CAPABILITY_ENVELOPE_TOKEN_OVERHEAD = 80


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
        return _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD + sum(
            item.estimated_tokens for item in self.operations
        )


@dataclass(frozen=True, slots=True)
class _OperationRegistration:
    """Private binding between an advertised handle and its implemented service."""

    operation: ResearchOperation
    handler: Callable[..., object]


_OPERATION_REGISTRATIONS = (
    # Each advertised operation maps to a public application-service method.
    # Deeper handle resolution and representation expansion remain intentionally
    # absent until their application services are implemented.
    _OperationRegistration(
        ResearchOperation("research.discover", "discover", "Find provider-backed candidates.", 24),
        DiscoveryService.discover,
    ),
    _OperationRegistration(
        ResearchOperation("research.verify", "verify", "Record an evidence assessment.", 24),
        EvidenceVerificationService.record,
    ),
)


def research_capabilities() -> ResearchCapabilities:
    """Return the intentionally compact first step of progressive tool discovery."""
    return ResearchCapabilities(
        version="1", operations=tuple(item.operation for item in _OPERATION_REGISTRATIONS)
    )
