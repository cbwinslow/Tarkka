import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.ingest import IngestResult, IngestService
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces import mcp
from tarkka.interfaces.mcp import create_server


def _ingest_document(tmp_path: Path) -> tuple[IngestResult, JsonResearchRepository]:
    source = tmp_path / "paper.md"
    source.write_text(
        "# Abstract\nEvidence first.\n\n# Methods\nTemporal validation.\n", encoding="utf-8"
    )
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    return result, documents


def _call(server: Any, tool_name: str, arguments: dict[str, object]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def test_mcp_server_registers_only_read_only_initial_operations() -> None:
    tools = asyncio.run(create_server().list_tools())

    assert [tool.name for tool in tools] == [
        "research_capabilities",
        "research_operation_schema",
        "document_manifest",
        "document_sections",
        "document_section",
    ]
    assert all(tool.annotations is not None and tool.annotations.read_only_hint for tool in tools)
    assert all(tool.annotations is not None and tool.annotations.idempotent_hint for tool in tools)


def test_mcp_server_defers_default_backend_construction_until_a_document_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unavailable_backend() -> DocumentRetrievalService:
        nonlocal calls
        calls += 1
        raise RuntimeError("document backend is unavailable")

    monkeypatch.setattr(mcp, "_document_retrieval_service", unavailable_backend)
    server = create_server()

    assert [tool.name for tool in asyncio.run(server.list_tools())] == [
        "research_capabilities",
        "research_operation_schema",
        "document_manifest",
        "document_sections",
        "document_section",
    ]
    assert _call(server, "research_capabilities", {})["ok"] is True
    assert calls == 0

    unavailable = _call(server, "document_manifest", {"document_id": str(uuid4())})
    assert unavailable["error"]["code"] == "backend_unavailable"
    assert calls == 1


def test_mcp_server_preserves_staged_document_disclosure(tmp_path: Path) -> None:
    result, documents = _ingest_document(tmp_path)
    server = create_server(documents=DocumentRetrievalService(documents=documents))

    capabilities = _call(server, "research_capabilities", {})
    assert capabilities["ok"] is True
    assert capabilities["estimated_tokens"] < 250
    assert "inputs" not in capabilities["operations"][0]

    schema = _call(
        server,
        "research_operation_schema",
        {"operation_id": "research.documents.sections"},
    )
    assert schema["ok"] is True
    assert [field["name"] for field in schema["inputs"]] == ["document_id", "offset", "limit"]

    manifest = _call(
        server,
        "document_manifest",
        {"document_id": f"doc:{result.document.document_id}"},
    )
    assert manifest == {"ok": True, "manifest": result.manifest.to_dict()}

    listing = _call(
        server,
        "document_sections",
        {"document_id": str(result.document.document_id), "limit": 1},
    )
    assert listing["total"] == 2
    assert len(listing["sections"]) == 1
    assert "text" not in listing["sections"][0]

    detail = _call(
        server,
        "document_section",
        {
            "document_id": str(result.document.document_id),
            "section_id": listing["sections"][0]["section_id"],
        },
    )
    assert detail["section"]["passages"][0]["text"] == "Evidence first."


def test_mcp_server_returns_actionable_errors_without_expanding_unknown_content(
    tmp_path: Path,
) -> None:
    result, documents = _ingest_document(tmp_path)
    server = create_server(documents=DocumentRetrievalService(documents=documents))

    unknown_operation = _call(
        server, "research_operation_schema", {"operation_id": "research.expand"}
    )
    assert unknown_operation == {
        "ok": False,
        "error": {
            "code": "unknown_operation",
            "message": "unknown research operation: research.expand",
            "next_actions": ["research_capabilities"],
        },
    }

    invalid_document = _call(server, "document_manifest", {"document_id": "not-a-document"})
    assert invalid_document["ok"] is False
    assert invalid_document["error"]["code"] == "invalid_argument"

    missing_manifest = _call(server, "document_manifest", {"document_id": str(uuid4())})
    assert missing_manifest["error"]["code"] == "not_found"
    assert missing_manifest["error"]["next_actions"] == ["research_capabilities"]

    invalid_sections = _call(server, "document_sections", {"document_id": "not-a-document"})
    assert invalid_sections["error"]["code"] == "invalid_argument"

    missing_document = _call(server, "document_sections", {"document_id": str(uuid4())})
    assert missing_document["error"]["code"] == "not_found"
    assert missing_document["error"]["next_actions"] == ["document_manifest"]

    invalid_pagination = _call(
        server,
        "document_sections",
        {"document_id": str(result.document.document_id), "offset": -1},
    )
    assert invalid_pagination["error"]["code"] == "invalid_argument"

    invalid_section = _call(
        server,
        "document_section",
        {"document_id": str(result.document.document_id), "section_id": "not-a-section"},
    )
    assert invalid_section["error"]["code"] == "invalid_argument"

    missing_section = _call(
        server,
        "document_section",
        {"document_id": str(result.document.document_id), "section_id": str(uuid4())},
    )
    assert missing_section["error"]["code"] == "not_found"
    assert missing_section["error"]["next_actions"] == ["document_sections"]
