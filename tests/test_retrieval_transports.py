"""End-to-end contracts for the local lexical retrieval transports."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.application.ingest import IngestService
from tarkka.application.lexical_retrieval import LexicalRetrievalService
from tarkka.infrastructure.json_retrieval_index_store import JsonRetrievalSegmentStore
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces import mcp
from tarkka.interfaces.main import _parse_workspace_id, main
from tarkka.interfaces.mcp import create_server


def _call(server: Any, tool_name: str, arguments: dict[str, object]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _persist_document(home: Path) -> str:
    source = home / "paper.md"
    source.write_text("# Abstract\nEvidence first for retrieval.\n", encoding="utf-8")
    documents = JsonResearchRepository(home / "catalog.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(home / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    return str(result.document.document_id)


def test_workspace_id_parser_rejects_invalid_value() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="invalid workspace id"):
        _parse_workspace_id("workspace:not-a-uuid")


def test_cli_indexes_and_searches_one_exact_local_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    document_id = _persist_document(tmp_path)

    assert (
        main(
            [
                "retrieval",
                "index",
                document_id,
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 0
    )
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["document_id"] == document_id
    assert indexed["derivation_version"] == "v1"
    assert indexed["configuration_fingerprint"] == "whole-passage-v1"
    assert indexed["segment_count"] == 1

    assert (
        main(
            [
                "retrieval",
                "index",
                document_id,
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["index_id"] == indexed["index_id"]

    assert (
        main(
            [
                "retrieval",
                "index",
                document_id,
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "alternate-v1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["configuration_fingerprint"] == "alternate-v1"

    assert (
        main(
            [
                "retrieval",
                "search",
                document_id,
                "retrieval",
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 0
    )
    found = json.loads(capsys.readouterr().out)
    assert found["document_id"] == document_id
    assert found["hits"][0]["text"] == "Evidence first for retrieval."
    assert found["hits"][0]["source_spans"][0]["char_start"] == 0
    assert found["hits"][0]["source_spans"][0]["char_end"] == len("Evidence first for retrieval.")


def test_cli_rejects_missing_projection_and_over_limit_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    document_id = _persist_document(tmp_path)

    assert (
        main(
            [
                "retrieval",
                "search",
                document_id,
                "retrieval",
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 2
    )
    assert "retrieval index not found" in capsys.readouterr().err

    assert (
        main(
            [
                "retrieval",
                "search",
                document_id,
                "retrieval",
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
                "--limit",
                "101",
            ]
        )
        == 2
    )
    assert "must not exceed 100" in capsys.readouterr().err

    assert (
        main(
            [
                "retrieval",
                "search",
                document_id,
                " ",
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 2
    )
    assert "query text must not be blank" in capsys.readouterr().err

    assert (
        main(
            [
                "retrieval",
                "index",
                document_id,
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 0
    )
    capsys.readouterr()
    unknown_document = "00000000-0000-0000-0000-000000000001"
    assert (
        main(
            [
                "retrieval",
                "index",
                unknown_document,
                "--derivation-version",
                "v1",
                "--configuration-fingerprint",
                "whole-passage-v1",
            ]
        )
        == 2
    )
    assert "document not found" in capsys.readouterr().err


def test_mcp_search_is_read_only_discoverable_and_preserves_source_spans(tmp_path: Path) -> None:
    document_id = _persist_document(tmp_path)
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    lexical = LexicalRetrievalService(
        documents=documents,
        indexes=JsonRetrievalSegmentStore(tmp_path / "retrieval_indexes.json"),
    )
    lexical.index(
        UUID(document_id),
        derivation_version="v1",
        configuration_fingerprint="whole-passage-v1",
    )
    server = create_server(lexical=lexical)

    capabilities = _call(server, "research_capabilities", {})
    assert "research.retrieval.search" in {
        operation["operation_id"] for operation in capabilities["operations"]
    }
    schema = _call(
        server, "research_operation_schema", {"operation_id": "research.retrieval.search"}
    )
    assert schema["operation"]["operation_id"] == "research.retrieval.search"

    response = _call(
        server,
        "retrieval_search",
        {
            "document_id": document_id,
            "query": "retrieval",
            "derivation_version": "v1",
            "configuration_fingerprint": "whole-passage-v1",
            "limit": 1,
        },
    )
    assert response["ok"] is True
    assert response["hits"][0]["text"] == "Evidence first for retrieval."
    assert response["hits"][0]["source_spans"][0]["char_start"] == 0

    tool = next(
        item for item in asyncio.run(server.list_tools()) if item.name == "retrieval_search"
    )
    assert tool.annotations is not None and tool.annotations.read_only_hint is True


def test_mcp_search_rejects_invalid_or_missing_exact_projection(tmp_path: Path) -> None:
    document_id = _persist_document(tmp_path)
    lexical = LexicalRetrievalService(
        documents=JsonResearchRepository(tmp_path / "catalog.json"),
        indexes=JsonRetrievalSegmentStore(tmp_path / "retrieval_indexes.json"),
    )
    server = create_server(lexical=lexical)
    request = {
        "document_id": document_id,
        "query": "retrieval",
        "derivation_version": "v1",
        "configuration_fingerprint": "whole-passage-v1",
    }

    missing = _call(server, "retrieval_search", request)
    assert missing["error"]["code"] == "not_found"

    for limit in (101, 0, -1):
        invalid_limit = _call(server, "retrieval_search", {**request, "limit": limit})
        assert invalid_limit["error"]["code"] == "invalid_argument"

    for field in ("document_id", "query", "derivation_version", "configuration_fingerprint"):
        response = _call(server, "retrieval_search", {**request, field: ""})
        assert response["error"]["code"] == "invalid_argument"

    missing_document = _call(
        server,
        "retrieval_search",
        {**request, "document_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert missing_document["error"]["code"] == "not_found"


def test_mcp_search_lazily_translates_an_unavailable_default_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> LexicalRetrievalService:
        raise RuntimeError("retrieval backend unavailable")

    monkeypatch.setattr(mcp, "_lexical_retrieval_service", unavailable)
    response = _call(
        create_server(),
        "retrieval_search",
        {
            "document_id": "00000000-0000-0000-0000-000000000001",
            "query": "retrieval",
            "derivation_version": "v1",
            "configuration_fingerprint": "whole-passage-v1",
        },
    )
    assert response["error"]["code"] == "backend_unavailable"
