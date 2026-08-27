import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.jsonl_telemetry import JsonlAgentUsageRecorder


def _event(
    *,
    interface: str = "mcp",
    operation_id: str = "document_manifest",
    outcome: str = "success",
    elapsed_ms: int = 12,
    response_bytes: int = 345,
    estimated_tokens: int = 42,
    error_code: str | None = None,
) -> AgentUsageEvent:
    return AgentUsageEvent(
        occurred_at=datetime(2026, 8, 25, tzinfo=UTC),
        interface=interface,
        operation_id=operation_id,
        outcome=outcome,
        elapsed_ms=elapsed_ms,
        response_bytes=response_bytes,
        estimated_tokens=estimated_tokens,
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
    ("kwargs", "message"),
    [
        ({"interface": " "}, "non-blank"),
        ({"operation_id": "\t"}, "non-blank"),
        ({"outcome": "other"}, "outcome"),
        ({"elapsed_ms": -1}, "non-negative"),
        ({"response_bytes": -1}, "non-negative"),
        ({"estimated_tokens": -1}, "non-negative"),
        ({"outcome": "success", "error_code": "not_found"}, "successful"),
        ({"outcome": "error", "error_code": None}, "require"),
        ({"outcome": "error", "error_code": "  "}, "require"),
    ],
)
def test_agent_usage_event_rejects_invalid_measurements_and_outcomes(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _event(**kwargs)  # type: ignore[arg-type]
