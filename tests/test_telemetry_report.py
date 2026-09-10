from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.jsonl_telemetry import JsonlAgentUsageRecorder
from tarkka.interfaces.entrypoint import main


def _event(operation_id: str, *, outcome: str = "success", tokens: int = 10) -> AgentUsageEvent:
    return AgentUsageEvent(
        occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
        interface="mcp",
        operation_id=operation_id,
        outcome=outcome,
        elapsed_ms=tokens * 2,
        response_bytes=tokens * 4,
        estimated_tokens=tokens,
        error_code="invalid_argument" if outcome == "error" else None,
    )


def test_telemetry_report_aggregates_and_ranks_operations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "usage.jsonl"
    recorder = JsonlAgentUsageRecorder(path)
    recorder.record(_event("document_section", tokens=30))
    recorder.record(_event("document_manifest", tokens=10))
    recorder.record(_event("document_section", outcome="error", tokens=20))

    assert main(["telemetry", "report", str(path), "--limit", "1"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["event_count"] == 3
    assert report["success_count"] == 2
    assert report["error_count"] == 1
    assert report["estimated_tokens"] == 60
    assert report["response_bytes"] == 240
    assert report["elapsed_ms"] == 120
    assert report["operations"] == [
        {
            "operation_id": "document_section",
            "event_count": 2,
            "success_count": 1,
            "error_count": 1,
            "estimated_tokens": 50,
            "response_bytes": 200,
            "elapsed_ms": 100,
        }
    ]


def test_telemetry_report_handles_empty_and_malformed_ledgers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.touch()
    assert main(["telemetry", "report", str(empty)]) == 0
    assert json.loads(capsys.readouterr().out)["event_count"] == 0

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text('{"operation_id":"leak-me"}\n', encoding="utf-8")
    assert main(["telemetry", "report", str(malformed)]) == 2
    error = capsys.readouterr().err
    assert "line 1" in error
    assert "leak-me" not in error

    malformed.write_text("[]\n", encoding="utf-8")
    assert main(["telemetry", "report", str(malformed)]) == 2
    assert "line 1" in capsys.readouterr().err

    baseline = {
        "occurred_at": "2026-09-09T00:00:00+00:00",
        "interface": "mcp",
        "operation_id": "document_manifest",
        "outcome": "success",
        "elapsed_ms": 1,
        "response_bytes": 1,
        "estimated_tokens": 1,
        "error_code": None,
    }
    for field, value in (("interface", 1), ("elapsed_ms", True), ("response_bytes", 1.5)):
        payload = {**baseline, field: value}
        malformed.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        assert main(["telemetry", "report", str(malformed)]) == 2
        error = capsys.readouterr().err
        assert "line 1" in error
        assert "Traceback" not in error


def test_telemetry_report_rejects_invalid_limit_and_missing_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["telemetry", "report", str(tmp_path / "missing.jsonl")]) == 2
    assert "unable to read telemetry ledger" in capsys.readouterr().err

    path = tmp_path / "usage.jsonl"
    path.touch()
    assert main(["telemetry", "report", str(path), "--limit", "0"]) == 2
    assert "positive integer" in capsys.readouterr().err


def test_telemetry_entrypoint_uses_process_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "usage.jsonl"
    path.touch()
    monkeypatch.setattr(sys, "argv", ["tarkka", "telemetry", "report", str(path)])

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["operations"] == []
