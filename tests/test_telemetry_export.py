from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tarkka.domain.telemetry import AgentUsageEvent, AgentUsageExport
from tarkka.ports.telemetry import AgentUsageExporter, export_agent_usage


def _event(*, outcome: str = "success") -> AgentUsageEvent:
    return AgentUsageEvent(
        occurred_at=datetime(2026, 9, 10, tzinfo=UTC),
        interface="mcp",
        operation_id="document_manifest",
        outcome=outcome,
        elapsed_ms=12,
        response_bytes=345,
        estimated_tokens=42,
        error_code="invalid_argument" if outcome == "error" else None,
    )


class _Exporter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.exports: list[AgentUsageExport] = []

    def export(self, event: AgentUsageExport) -> None:
        if self.error is not None:
            raise self.error
        self.exports.append(event)


def test_usage_export_contains_only_permitted_aggregate_fields() -> None:
    exported = AgentUsageExport.from_event(_event(outcome="error"))

    assert exported.to_dict() == {
        "occurred_at": "2026-09-10T00:00:00+00:00",
        "interface": "mcp",
        "operation_id": "document_manifest",
        "outcome": "error",
        "elapsed_ms": 12,
        "response_bytes": 345,
        "estimated_tokens": 42,
        "error_code": "invalid_argument",
    }
    assert "prompt" not in exported.to_dict()
    assert "document_id" not in exported.to_dict()


def test_exporter_protocol_receives_stable_payload_and_is_fail_safe() -> None:
    exporter: AgentUsageExporter = _Exporter()

    assert export_agent_usage(exporter, _event()) is True
    assert exporter.exports == [AgentUsageExport.from_event(_event())]

    failing: AgentUsageExporter = _Exporter(RuntimeError("export unavailable"))
    assert export_agent_usage(failing, _event()) is False


@pytest.mark.parametrize(
    ("outcome", "error_code", "message"),
    [("other", None, "outcome"), ("success", "failure", "successful")],
)
def test_usage_export_preserves_event_validation(
    outcome: str, error_code: str | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        AgentUsageExport.from_event(
            AgentUsageEvent(
                occurred_at=datetime(2026, 9, 10, tzinfo=UTC),
                interface="mcp",
                operation_id="document_manifest",
                outcome=outcome,
                elapsed_ms=0,
                response_bytes=0,
                estimated_tokens=0,
                error_code=error_code,
            )
        )
