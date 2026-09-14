from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.application.proof_bundle_exports import ProofBundleExportReceipt
from tarkka.infrastructure.proof_bundles import ProofBundleVerification
from tarkka.interfaces.mcp import create_server

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
