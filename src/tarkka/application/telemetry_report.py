"""Aggregate, privacy-safe reports over locally recorded agent usage events."""

from __future__ import annotations

from dataclasses import dataclass

from tarkka.domain.telemetry import AgentUsageEvent


@dataclass(frozen=True, slots=True)
class OperationUsageSummary:
    operation_id: str
    event_count: int
    success_count: int
    error_count: int
    estimated_tokens: int
    response_bytes: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "operation_id": self.operation_id,
            "event_count": self.event_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "estimated_tokens": self.estimated_tokens,
            "response_bytes": self.response_bytes,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class AgentUsageReport:
    event_count: int
    success_count: int
    error_count: int
    estimated_tokens: int
    response_bytes: int
    elapsed_ms: int
    operations: tuple[OperationUsageSummary, ...]

    def to_dict(self) -> dict[str, int | list[dict[str, int | str]]]:
        return {
            "event_count": self.event_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "estimated_tokens": self.estimated_tokens,
            "response_bytes": self.response_bytes,
            "elapsed_ms": self.elapsed_ms,
            "operations": [item.to_dict() for item in self.operations],
        }


def agent_usage_report(
    events: tuple[AgentUsageEvent, ...], *, limit: int = 20
) -> AgentUsageReport:
    """Aggregate events into a deterministic, bounded operation-cost report."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("telemetry report limit must be a positive integer")
    grouped: dict[str, list[AgentUsageEvent]] = {}
    for event in events:
        grouped.setdefault(event.operation_id, []).append(event)
    operations = tuple(
        sorted(
            (
                OperationUsageSummary(
                    operation_id=operation_id,
                    event_count=len(items),
                    success_count=sum(item.outcome == "success" for item in items),
                    error_count=sum(item.outcome == "error" for item in items),
                    estimated_tokens=sum(item.estimated_tokens for item in items),
                    response_bytes=sum(item.response_bytes for item in items),
                    elapsed_ms=sum(item.elapsed_ms for item in items),
                )
                for operation_id, items in grouped.items()
            ),
            key=lambda item: (-item.estimated_tokens, item.operation_id),
        )[:limit]
    )
    return AgentUsageReport(
        event_count=len(events),
        success_count=sum(event.outcome == "success" for event in events),
        error_count=sum(event.outcome == "error" for event in events),
        estimated_tokens=sum(event.estimated_tokens for event in events),
        response_bytes=sum(event.response_bytes for event in events),
        elapsed_ms=sum(event.elapsed_ms for event in events),
        operations=operations,
    )
