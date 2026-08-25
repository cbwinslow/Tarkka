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
