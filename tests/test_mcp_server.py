import asyncio
import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.application.claim_lineage import (
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineagePaginationError,
    ClaimLineageService,
)
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.ingest import IngestResult, IngestService
from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces import mcp, why_cli
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service
from tarkka.interfaces.mcp import create_server
from tests.support.claim_lineage import persist_local_claim_lineage


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


class _TelemetryRecorder:
    def __init__(self) -> None:
        self.events: list[AgentUsageEvent] = []

    def record(self, event: AgentUsageEvent) -> None:
        self.events.append(event)


class _RaisingLineageService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def inspect(self, *_args: object, **_kwargs: object) -> object:
        raise self.error


def test_mcp_server_registers_only_read_only_initial_operations() -> None:
    tools = asyncio.run(create_server().list_tools())

    assert [tool.name for tool in tools] == [
        "research_capabilities",
        "research_operation_schema",
        "claim_lineage",
        "document_manifest",
        "document_sections",
        "document_section",
    ]
    assert all(tool.annotations is not None and tool.annotations.read_only_hint for tool in tools)
    assert all(tool.annotations is not None and tool.annotations.idempotent_hint for tool in tools)
    assert all(
        tool.annotations is not None and not tool.annotations.open_world_hint for tool in tools
    )


def test_mcp_server_defers_default_backend_construction_until_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_calls = 0
    lineage_calls = 0

    def unavailable_document_backend() -> DocumentRetrievalService:
        nonlocal document_calls
        document_calls += 1
        raise RuntimeError("document backend is unavailable")

    def unavailable_lineage_backend() -> ClaimLineageService:
        nonlocal lineage_calls
        lineage_calls += 1
        raise RuntimeError("lineage backend is unavailable")

    monkeypatch.setattr(mcp, "_document_retrieval_service", unavailable_document_backend)
    monkeypatch.setattr(mcp, "configured_claim_lineage_service", unavailable_lineage_backend)
    server = create_server()

    assert _call(server, "research_capabilities", {})["ok"] is True
    assert document_calls == 0
    assert lineage_calls == 0

    unavailable_document = _call(server, "document_manifest", {"document_id": str(uuid4())})
    assert unavailable_document["error"]["code"] == "backend_unavailable"
    assert document_calls == 1

    unavailable_lineage = _call(server, "claim_lineage", {"claim_id": str(uuid4())})
    assert unavailable_lineage["error"]["code"] == "backend_unavailable"
    assert lineage_calls == 1


def test_mcp_server_preserves_staged_document_disclosure(tmp_path: Path) -> None:
    result, documents = _ingest_document(tmp_path)
    server = create_server(documents=DocumentRetrievalService(documents=documents))

    capabilities = _call(server, "research_capabilities", {})
    assert capabilities["ok"] is True
    assert capabilities["estimated_tokens"] < 275
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
    assert detail["estimated_tokens"] > 0


def test_mcp_claim_lineage_matches_shared_view_and_cli_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(tmp_path / "state")
    service = claim_lineage_service(home=tmp_path / "state")
    server = create_server(lineage=service)

    arguments = {
        "claim_id": f"claim:{fixture.claim.extraction_id}",
        "offset": 0,
        "limit": 1,
        "evidence_offset": 1,
        "evidence_limit": 2,
    }
    response = _call(server, "claim_lineage", arguments)
    expected = claim_lineage_view(
        service.inspect(
            fixture.claim.extraction_id,
            offset=0,
            limit=1,
            evidence_offset=1,
            evidence_limit=2,
        ),
        offset=0,
        limit=1,
        evidence_offset=1,
        evidence_limit=2,
    )
    assert response["ok"] is True
    assert response["lineage"] == expected
    assert response["lineage"]["claim_evidence_page"] == {
        "offset": 1,
        "limit": 2,
        "total": 4,
    }
    assert len(response["lineage"]["claim_evidence"]) == 2
    assert response["estimated_tokens"] > 0

    monkeypatch.setattr(why_cli, "claim_lineage_service", lambda: service)
    assert (
        why_cli.main(
            [
                str(fixture.claim.extraction_id),
                "--limit",
                "1",
                "--evidence-offset",
                "1",
                "--evidence-limit",
                "2",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == response["lineage"]


def test_mcp_claim_lineage_schema_is_discoverable_without_full_schema_in_index() -> None:
    server = create_server()
    capabilities = _call(server, "research_capabilities", {})
    lineage_handle = next(
        item
        for item in capabilities["operations"]
        if item["operation_id"] == "research.claims.lineage"
    )

    assert lineage_handle["family"] == "explain"
    assert "inputs" not in lineage_handle

    schema = _call(
        server,
        "research_operation_schema",
        {"operation_id": "research.claims.lineage"},
    )
    assert [field["name"] for field in schema["inputs"]] == [
        "claim_id",
        "offset",
        "limit",
        "evidence_offset",
        "evidence_limit",
    ]
    assert schema["inputs"][1]["maximum"] == 10_000
    assert schema["inputs"][2]["maximum"] == 100
    assert schema["inputs"][3]["maximum"] == 10_000
    assert schema["inputs"][4]["maximum"] == 100


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ClaimLineageClaimNotFoundError("missing claim"), "claim_not_found"),
        (ClaimLineageEvidenceNotFoundError("missing evidence"), "evidence_not_found"),
        (
            ClaimLineageExtractionRunNotFoundError("missing run"),
            "extraction_run_not_found",
        ),
        (ClaimLineageDocumentNotFoundError("missing document"), "document_not_found"),
        (ClaimLineageArtifactNotFoundError("missing artifact"), "artifact_not_found"),
        (
            ClaimLineageCitationRepositoryUnavailableError("no citation store"),
            "citation_repository_unavailable",
        ),
        (
            ClaimLineageCitationContextNotFoundError("missing context"),
            "citation_context_not_found",
        ),
        (ClaimLineageMismatchError("mismatch"), "lineage_mismatch"),
        (ClaimLineagePaginationError("bad pagination"), "invalid_argument"),
        (ValueError("corrupt persisted value"), "backend_unavailable"),
        (OSError("backend unavailable"), "backend_unavailable"),
        (RuntimeError("backend unavailable"), "backend_unavailable"),
    ],
)
def test_mcp_claim_lineage_maps_expected_failures(
    error: Exception,
    expected_code: str,
) -> None:
    service = cast(ClaimLineageService, _RaisingLineageService(error))
    response = _call(
        create_server(lineage=service),
        "claim_lineage",
        {"claim_id": str(uuid4())},
    )

    assert response["ok"] is False
    assert response["error"]["code"] == expected_code


def test_mcp_claim_lineage_rejects_invalid_handles_before_backend_work() -> None:
    service = cast(
        ClaimLineageService,
        _RaisingLineageService(AssertionError("backend should not be called")),
    )
    server = create_server(lineage=service)

    for malformed_id in (None, 7, {"id": "claim"}, "not-a-claim"):
        response = _call(server, "claim_lineage", {"claim_id": malformed_id})
        assert response["error"]["code"] == "invalid_argument"


def test_mcp_claim_lineage_refuses_oversized_payloads_with_recoverable_paging_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(tmp_path / "state")
    service = claim_lineage_service(home=tmp_path / "state")
    monkeypatch.setattr(mcp, "_MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS", 0)

    response = _call(
        create_server(lineage=service),
        "claim_lineage",
        {"claim_id": str(fixture.claim.extraction_id)},
    )

    assert response["error"]["code"] == "content_too_large"
    assert "smaller evidence_limit" in response["error"]["message"]
    assert response["error"]["next_actions"] == ["claim_lineage"]


def test_mcp_server_emits_opt_in_aggregate_usage_without_source_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    result, documents = _ingest_document(tmp_path)
    fixture = persist_local_claim_lineage(tmp_path / "lineage")
    telemetry = _TelemetryRecorder()
    server = create_server(
        documents=DocumentRetrievalService(documents=documents),
        lineage=claim_lineage_service(home=tmp_path / "lineage"),
        telemetry=telemetry,
    )

    _call(server, "document_manifest", {"document_id": str(result.document.document_id)})
    _call(server, "document_manifest", {"document_id": "not-a-document"})
    _call(server, "claim_lineage", {"claim_id": str(fixture.claim.extraction_id), "limit": 1})

    observed = [(event.operation_id, event.outcome, event.error_code) for event in telemetry.events]
    assert observed == [
        ("document_manifest", "success", None),
        ("document_manifest", "error", "invalid_argument"),
        ("claim_lineage", "success", None),
    ]
    assert all(event.interface == "mcp" and event.elapsed_ms >= 0 for event in telemetry.events)
    assert all(
        event.response_bytes > 0 and event.estimated_tokens >= 0 for event in telemetry.events
    )
    assert all("Evidence first." not in repr(event) for event in telemetry.events)
    assert all(fixture.claim.text not in repr(event) for event in telemetry.events)


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

    for malformed_id in (None, 7, {"id": "document"}):
        malformed_document = _call(server, "document_manifest", {"document_id": malformed_id})
        assert malformed_document["error"]["code"] == "invalid_argument"

    malformed_operation = _call(server, "research_operation_schema", {"operation_id": None})
    assert malformed_operation["error"]["code"] == "invalid_argument"

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

    malformed_section = _call(
        server,
        "document_section",
        {"document_id": str(result.document.document_id), "section_id": {"id": "section"}},
    )
    assert malformed_section["error"]["code"] == "invalid_argument"


def test_mcp_server_refuses_an_unbounded_section_expansion(tmp_path: Path) -> None:
    source = tmp_path / "long.md"
    source.write_text("# Long\n" + ("x" * 32_001), encoding="utf-8")
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    server = create_server(documents=DocumentRetrievalService(documents=documents))

    response = _call(
        server,
        "document_section",
        {
            "document_id": str(result.document.document_id),
            "section_id": str(result.document.sections[0].section_id),
        },
    )

    assert response["error"]["code"] == "content_too_large"
    assert response["error"]["next_actions"] == ["document_sections"]
