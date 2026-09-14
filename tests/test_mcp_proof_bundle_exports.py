from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import UUID

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.application.proof_bundle_exports import (
    ProofBundleExportConfigurationError,
    ProofBundleExportReceipt,
    ProofBundleExportService,
    ProofBundleHandleError,
    RetainedProofBundleNotFoundError,
    RetainedProofBundleVerificationError,
)
from tarkka.application.proof_bundles import ProofBundleDocumentNotFoundError, ProofBundleV3Service
from tarkka.infrastructure.proof_bundles import ProofBundleVerification
from tarkka.interfaces import mcp, proof_bundle_export_runtime
from tarkka.interfaces.mcp import create_server
from tarkka.ports.artifacts import ArtifactStore

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fe01")
_BUNDLE_SHA256 = "a" * 64


def _call(server: Any, tool_name: str, arguments: dict[str, object]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _verification() -> ProofBundleVerification:
    return ProofBundleVerification(
        bundle_sha256=_BUNDLE_SHA256,
        document_id=str(_DOCUMENT_ID),
        artifact_sha256="b" * 64,
        artifact_size_bytes=7,
        member_count=4,
    )


class _Exports:
    def __init__(self) -> None:
        self.exported: list[UUID] = []
        self.verified: list[object] = []

    def export(self, document_id: UUID) -> ProofBundleExportReceipt:
        self.exported.append(document_id)
        return ProofBundleExportReceipt(
            handle=f"bundle:sha256:{_BUNDLE_SHA256}",
            schema_version=3,
            byte_count=123,
            document_id=str(document_id),
            artifact_sha256="b" * 64,
            verification=_verification(),
        )

    def verify(self, bundle_handle: object) -> ProofBundleVerification:
        self.verified.append(bundle_handle)
        return _verification()


class _FailingExports:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def export(self, document_id: UUID) -> ProofBundleExportReceipt:
        raise self._error

    def verify(self, bundle_handle: object) -> ProofBundleVerification:
        raise self._error


def test_mcp_proof_bundle_tools_are_discoverable_explicit_writes() -> None:
    server = create_server()
    capabilities = _call(server, "research_capabilities", {})
    operation_ids = {item["operation_id"] for item in capabilities["operations"]}
    assert {
        "research.proof_bundles.export",
        "research.proof_bundles.verify",
    } <= operation_ids

    schema = _call(
        server,
        "research_operation_schema",
        {"operation_id": "research.proof_bundles.verify"},
    )
    assert [field["name"] for field in schema["inputs"]] == ["bundle_handle"]

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert tools["proof_bundle_export"].annotations is not None
    assert tools["proof_bundle_verify"].annotations is not None
    assert tools["proof_bundle_export"].annotations.read_only_hint is False
    assert tools["proof_bundle_verify"].annotations.read_only_hint is False


def test_mcp_proof_bundle_export_and_verify_use_stable_handles() -> None:
    exports = _Exports()
    server = create_server(proof_bundles=exports)  # type: ignore[arg-type]

    exported = _call(server, "proof_bundle_export", {"document_id": f"doc:{_DOCUMENT_ID}"})
    verified = _call(
        server,
        "proof_bundle_verify",
        {"bundle_handle": exported["bundle"]["handle"]},
    )

    assert exported["bundle"]["verification"]["valid"] is True
    assert verified["verification"] == _verification().to_dict()
    assert exports.exported == [_DOCUMENT_ID]
    assert exports.verified == [f"bundle:sha256:{_BUNDLE_SHA256}"]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "error", "expected_code", "expected_next_action"),
    [
        (
            "proof_bundle_export",
            {"document_id": f"doc:{_DOCUMENT_ID}"},
            ProofBundleDocumentNotFoundError("document missing"),
            "not_found",
            "research.documents.manifest",
        ),
        (
            "proof_bundle_export",
            {"document_id": f"doc:{_DOCUMENT_ID}"},
            ProofBundleExportConfigurationError("misconfigured"),
            "backend_unavailable",
            None,
        ),
        (
            "proof_bundle_export",
            {"document_id": f"doc:{_DOCUMENT_ID}"},
            RetainedProofBundleVerificationError("corrupt"),
            "verification_failed",
            None,
        ),
        (
            "proof_bundle_export",
            {"document_id": f"doc:{_DOCUMENT_ID}"},
            OSError("unavailable"),
            "backend_unavailable",
            None,
        ),
        (
            "proof_bundle_verify",
            {"bundle_handle": f"bundle:sha256:{_BUNDLE_SHA256}"},
            ProofBundleHandleError("malformed"),
            "invalid_argument",
            None,
        ),
        (
            "proof_bundle_verify",
            {"bundle_handle": f"bundle:sha256:{_BUNDLE_SHA256}"},
            RetainedProofBundleNotFoundError("missing"),
            "not_found",
            "research.proof_bundles.export",
        ),
        (
            "proof_bundle_verify",
            {"bundle_handle": f"bundle:sha256:{_BUNDLE_SHA256}"},
            RetainedProofBundleVerificationError("corrupt"),
            "verification_failed",
            None,
        ),
        (
            "proof_bundle_verify",
            {"bundle_handle": f"bundle:sha256:{_BUNDLE_SHA256}"},
            OSError("unavailable"),
            "backend_unavailable",
            None,
        ),
    ],
)
def test_mcp_proof_bundle_tools_map_failures_without_leaking_backend_details(
    tool_name: str,
    arguments: dict[str, object],
    error: Exception,
    expected_code: str,
    expected_next_action: str | None,
) -> None:
    server = create_server(proof_bundles=_FailingExports(error))  # type: ignore[arg-type]

    response = _call(server, tool_name, arguments)

    assert response["ok"] is False
    assert response["error"]["code"] == expected_code
    if expected_next_action is None:
        assert response["error"]["next_actions"] == []
    else:
        assert response["error"]["next_actions"] == [expected_next_action]


def test_mcp_proof_bundle_service_is_lazy_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    exports = _Exports()
    calls = 0

    def configured_exports() -> ProofBundleExportService:
        nonlocal calls
        calls += 1
        return cast(ProofBundleExportService, exports)

    monkeypatch.setattr(mcp, "proof_bundle_export_service", configured_exports)
    server = create_server()

    assert _call(server, "proof_bundle_export", {"document_id": "not-a-document"})["ok"] is False
    assert calls == 0

    _call(server, "proof_bundle_export", {"document_id": f"doc:{_DOCUMENT_ID}"})
    _call(server, "proof_bundle_verify", {"bundle_handle": f"bundle:sha256:{_BUNDLE_SHA256}"})

    assert calls == 1


def test_proof_bundle_export_runtime_composes_v3_builder_and_artifact_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(ProofBundleV3Service, object())
    archives = cast(ArtifactStore, object())
    monkeypatch.setattr(proof_bundle_export_runtime, "proof_bundle_v3_service", lambda: builder)
    monkeypatch.setattr(
        proof_bundle_export_runtime, "proof_bundle_artifact_store", lambda: archives
    )

    service = proof_bundle_export_runtime.proof_bundle_export_service()

    assert service._bundles is builder
    assert service._archives is archives
