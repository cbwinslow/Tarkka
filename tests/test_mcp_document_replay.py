from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.application.document_replay import (
    DocumentReplayer,
    DocumentReplayExecutionError,
)
from tarkka.application.document_replay_protocol import document_replay_response
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayImplementation,
    ReplayResult,
    ReplayStatus,
)
from tarkka.interfaces import mcp
from tarkka.interfaces.mcp import create_server

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fe01")


def _call(server: Any, tool_name: str, arguments: dict[str, object]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _result() -> ReplayResult:
    return ReplayResult(
        status=ReplayStatus.MATCHED,
        bundle_sha256="a" * 64,
        document_id=str(_DOCUMENT_ID),
        expected_sha256="b" * 64,
        actual_sha256="b" * 64,
        determinism=ReplayDeterminism.DETERMINISTIC,
        implementation=ReplayImplementation(
            parser_name="plain-text",
            parser_version="3",
            tarkka_version="0.1.0",
            python_implementation="CPython",
            python_version="3.test",
        ),
    )


class _ReplayService:
    def __init__(self, outcome: ReplayResult | BaseException) -> None:
        self.outcome = outcome
        self.calls: list[UUID] = []

    def replay(self, document_id: UUID) -> ReplayResult:
        self.calls.append(document_id)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_mcp_document_replay_matches_shared_transport_contract() -> None:
    service = _ReplayService(_result())
    server = create_server(replay=service)

    response = _call(
        server,
        "document_replay",
        {"document_id": f"doc:{_DOCUMENT_ID}"},
    )

    assert response == document_replay_response(service, _DOCUMENT_ID)
    assert service.calls == [_DOCUMENT_ID, _DOCUMENT_ID]
    assert response["replay"]["status"] == "matched"


def test_mcp_document_replay_rejects_invalid_handle_before_backend() -> None:
    service = _ReplayService(AssertionError("backend must not be called"))
    server = create_server(replay=service)

    for value in (None, 7, {"id": "document"}, "not-a-document"):
        response = _call(server, "document_replay", {"document_id": value})
        assert response["error"]["code"] == "invalid_argument"

    assert service.calls == []


def test_mcp_document_replay_preserves_shared_machine_problem() -> None:
    service = _ReplayService(
        DocumentReplayExecutionError(
            "replay_parser_unavailable",
            "exact parser unavailable",
            parser_name="fixture",
            parser_version="9",
        )
    )

    response = _call(
        create_server(replay=service),
        "document_replay",
        {"document_id": str(_DOCUMENT_ID)},
    )

    assert response["ok"] is False
    assert response["error"] == {
        "code": "replay_parser_unavailable",
        "message": "exact parser unavailable",
        "next_actions": [],
    }


def test_mcp_document_replay_runtime_is_lazy_and_configuration_failures_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unavailable() -> DocumentReplayer:
        nonlocal calls
        calls += 1
        raise ValueError("TARKKA_DATABASE_URL is required")

    monkeypatch.setattr(mcp, "configured_document_replay_service", unavailable)
    server = create_server()

    assert _call(server, "research_capabilities", {})["ok"] is True
    assert calls == 0

    response = _call(
        server,
        "document_replay",
        {"document_id": str(_DOCUMENT_ID)},
    )

    assert response["error"]["code"] == "backend_unavailable"
    assert calls == 1


def test_mcp_document_replay_schema_is_progressively_discoverable() -> None:
    server = create_server()
    capabilities = _call(server, "research_capabilities", {})
    replay = next(
        item
        for item in capabilities["operations"]
        if item["operation_id"] == "research.documents.replay"
    )

    assert replay["family"] == "replay"
    assert "inputs" not in replay

    schema = _call(
        server,
        "research_operation_schema",
        {"operation_id": "research.documents.replay"},
    )
    assert [field["name"] for field in schema["inputs"]] == ["document_id"]
