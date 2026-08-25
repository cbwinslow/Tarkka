import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.jsonl_telemetry import JsonlAgentUsageRecorder


def _event(*, outcome: str = "success", error_code: str | None = None) -> AgentUsageEvent:
    return AgentUsageEvent(
        occurred_at=datetime(2026, 8, 25, tzinfo=UTC),
        interface="mcp",
        operation_id="document_manifest",
        outcome=outcome,
        elapsed_ms=12,
        response_bytes=345,
        estimated_tokens=42,
        error_code=error_code,
    )


def test_jsonl_agent_usage_recorder_persists_only_aggregate_measurements(tmp_path: Path) -> None:
    path = tmp_path / "telemetry" / "usage.jsonl"
    JsonlAgentUsageRecorder(path).record(_event())

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "elapsed_ms": 12,
        "error_code": None,
        "estimated_tokens": 42,
        "interface": "mcp",
        "occurred_at": "2026-08-25T00:00:00+00:00",
        "operation_id": "document_manifest",
        "outcome": "success",
        "response_bytes": 345,
    }
    assert "document_id" not in payload
    assert "source" not in payload


@pytest.mark.parametrize(
    ("outcome", "error_code", "message"),
    [
        ("other", None, "outcome"),
        ("success", "not_found", "successful"),
        ("error", None, "require"),
    ],
)
def test_agent_usage_event_rejects_inconsistent_outcomes(
    outcome: str,
    error_code: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _event(outcome=outcome, error_code=error_code)
