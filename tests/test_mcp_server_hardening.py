from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.domain.models import Passage, Section
from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.jsonl_telemetry import JsonlAgentUsageRecorder
from tarkka.interfaces import mcp
from tarkka.interfaces.mcp import create_server


def _call(server: Any, tool_name: str, arguments: dict[str, object]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


class _UnavailableDocuments:
    def manifest(self, document_id: object) -> object:
        raise OSError("manifest unavailable")

    def sections(self, document_id: object, *, offset: int, limit: int) -> object:
        raise OSError("sections unavailable")

    def section(self, document_id: object, section_id: object) -> object:
        raise RuntimeError("section unavailable")


class _RecordingTelemetry:
    def __init__(self) -> None:
        self.events: list[AgentUsageEvent] = []

    def record(self, event: AgentUsageEvent) -> None:
        self.events.append(event)


class _FailingTelemetry:
    def record(self, event: AgentUsageEvent) -> None:
        raise RuntimeError("telemetry sink failed")


def test_mcp_document_tools_translate_backend_failures_without_leaking_exceptions() -> None:
    server = create_server(documents=_UnavailableDocuments())  # type: ignore[arg-type]

    sections = _call(
        server,
        "document_sections",
        {"document_id": str(uuid4()), "offset": 0, "limit": 1},
    )
    section = _call(
        server,
        "document_section",
        {"document_id": str(uuid4()), "section_id": str(uuid4())},
    )

    assert sections["error"]["code"] == "backend_unavailable"
    assert section["error"]["code"] == "backend_unavailable"


def test_mcp_document_section_reports_a_missing_document_before_section_lookup(
    tmp_path: Path,
) -> None:
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    server = create_server(documents=DocumentRetrievalService(documents=documents))

    response = _call(
        server,
        "document_section",
        {"document_id": str(uuid4()), "section_id": str(uuid4())},
    )

    assert response["error"]["code"] == "not_found"
    assert response["error"]["next_actions"] == ["document_manifest"]


def test_mcp_section_payload_preserves_parent_handle_and_exact_offsets() -> None:
    document_id = uuid4()
    parent_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="abc",
        char_start=4,
        char_end=7,
    )
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=1,
        title="Child",
        level=2,
        parent_section_id=parent_id,
        passages=(passage,),
    )

    payload = mcp._section_payload(section)

    assert payload["parent_section_id"] == str(parent_id)
    assert payload["passages"] == [
        {
            "passage_id": str(passage.passage_id),
            "ordinal": 0,
            "text": "abc",
            "char_start": 4,
            "char_end": 7,
        }
    ]


def test_mcp_telemetry_environment_is_explicit_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARKKA_MCP_TELEMETRY_PATH", raising=False)
    assert mcp._telemetry_from_environment() is None

    monkeypatch.setenv("TARKKA_MCP_TELEMETRY_PATH", "   ")
    assert mcp._telemetry_from_environment() is None

    path = tmp_path / "telemetry" / "usage.jsonl"
    monkeypatch.setenv("TARKKA_MCP_TELEMETRY_PATH", str(path))
    recorder = mcp._telemetry_from_environment()
    assert isinstance(recorder, JsonlAgentUsageRecorder)
    assert recorder.path == path.resolve()


def test_mcp_main_runs_stdio_with_environment_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("TARKKA_MCP_TELEMETRY_PATH", str(path))

    class _Server:
        def run(self, *, transport: str) -> None:
            observed["transport"] = transport

    def fake_create_server(*, telemetry: object = None) -> _Server:
        observed["telemetry"] = telemetry
        return _Server()

    monkeypatch.setattr(mcp, "create_server", fake_create_server)

    mcp.main()

    assert observed["transport"] == "stdio"
    assert isinstance(observed["telemetry"], JsonlAgentUsageRecorder)


def test_mcp_telemetry_failure_never_changes_tool_response() -> None:
    server = create_server(telemetry=_FailingTelemetry())

    response = _call(server, "research_capabilities", {})

    assert response["ok"] is True


def test_mcp_response_measurement_handles_disabled_and_non_integer_estimates() -> None:
    response: dict[str, object] = {
        "ok": True,
        "estimated_tokens": True,
        "error": {"code": 7},
    }
    mcp._record_response(None, "test_operation", response, 0.001)

    recorder = _RecordingTelemetry()
    mcp._record_response(recorder, "test_operation", response, 0.001)

    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.operation_id == "test_operation"
    assert event.outcome == "success"
    assert event.error_code is None
    assert event.estimated_tokens == 0
    assert event.elapsed_ms == 1
    assert event.response_bytes > 0
