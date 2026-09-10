"""Privacy-preserving measurements for agent-facing operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AgentUsageEvent:
    """One aggregate tool-response measurement without request or source content."""

    occurred_at: datetime
    interface: str
    operation_id: str
    outcome: str
    elapsed_ms: int
    response_bytes: int
    estimated_tokens: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.interface.strip() or not self.operation_id.strip():
            raise ValueError("telemetry interface and operation ID must be non-blank")
        if self.outcome not in {"success", "error"}:
            raise ValueError("telemetry outcome must be success or error")
        if any(
            value < 0 for value in (self.elapsed_ms, self.response_bytes, self.estimated_tokens)
        ):
            raise ValueError("telemetry measurements must be non-negative")
        if self.outcome == "success" and self.error_code is not None:
            raise ValueError("successful telemetry events must not contain an error code")
        if self.outcome == "error" and (self.error_code is None or not self.error_code.strip()):
            raise ValueError("failed telemetry events require a non-blank error code")


@dataclass(frozen=True, slots=True)
class AgentUsageExport:
    """Vendor-neutral aggregate payload suitable for optional telemetry export."""

    occurred_at: datetime
    interface: str
    operation_id: str
    outcome: str
    elapsed_ms: int
    response_bytes: int
    estimated_tokens: int
    error_code: str | None = None

    @classmethod
    def from_event(cls, event: AgentUsageEvent) -> AgentUsageExport:
        """Map one already-validated local measurement without adding content fields."""
        return cls(
            occurred_at=event.occurred_at,
            interface=event.interface,
            operation_id=event.operation_id,
            outcome=event.outcome,
            elapsed_ms=event.elapsed_ms,
            response_bytes=event.response_bytes,
            estimated_tokens=event.estimated_tokens,
            error_code=event.error_code,
        )

    def to_dict(self) -> dict[str, int | str | None]:
        """Return the complete, bounded export payload."""
        return {
            "occurred_at": self.occurred_at.isoformat(),
            "interface": self.interface,
            "operation_id": self.operation_id,
            "outcome": self.outcome,
            "elapsed_ms": self.elapsed_ms,
            "response_bytes": self.response_bytes,
            "estimated_tokens": self.estimated_tokens,
            "error_code": self.error_code,
        }
