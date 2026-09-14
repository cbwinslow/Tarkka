from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.proof_bundle_exports import (
    ProofBundleExportConfigurationError,
    ProofBundleExportService,
    ProofBundleHandleError,
    RetainedProofBundleNotFoundError,
    RetainedProofBundleVerificationError,
    parse_proof_bundle_handle,
)
from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.infrastructure.normalized_document_json import (
    canonical_normalized_document_bytes,
    normalized_document_descriptor,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    canonical_research_state_bytes,
    research_state_descriptor,
)
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tests.support.proof_bundles import proof_bundle_payload


class _Builder:
    def __init__(self, payload: ProofBundlePayload) -> None:
        self.payload = payload
        self.calls: list[UUID] = []

    def build(self, document_id: UUID) -> ProofBundlePayload:
        self.calls.append(document_id)
        return self.payload


def _v3_payload() -> ProofBundlePayload:
    base = proof_bundle_payload()
    document = Document(
        document_id=base.manifest.document.document_id,
        artifact_id=base.manifest.document.artifact_id,
        title=base.manifest.document.title,
        parser_name=base.manifest.document.parser_name,
        parser_version=base.manifest.document.parser_version,
        sections=(),
        normalized_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    state = canonical_research_state_bytes(
        {
            "format": "tarkka-document-research-state",
            "schema_version": 1,
            "document_id": str(document.document_id),
            "claims": [],
        }
    )
    normalized = canonical_normalized_document_bytes(document)
    manifest = ProofBundleManifestV3(
        document=base.manifest.document,
        artifact=base.manifest.artifact,
        research_state=research_state_descriptor(state),
        normalized_document=normalized_document_descriptor(normalized),
        work_documents=base.manifest.work_documents,
        source_observations=base.manifest.source_observations,
        resource_links=base.manifest.resource_links,
    )
    return ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=base.artifact_bytes,
        research_state_bytes=state,
        normalized_document_bytes=normalized,
    )


def test_export_retains_a_v3_bundle_and_verifies_its_stable_handle(tmp_path: Path) -> None:
    payload = _v3_payload()
    builder = _Builder(payload)
    service = ProofBundleExportService(
        bundles=builder, archives=LocalArtifactStore(tmp_path / "artifacts")
    )

    first = service.export(payload.manifest.document.document_id)
    second = service.export(payload.manifest.document.document_id)

    assert first.handle == second.handle
    assert first.schema_version == 3
    assert first.byte_count > 0
    assert first.to_dict()["handle"] == first.handle
    assert first.verification.to_dict()["valid"] is True
    assert service.verify(first.handle) == first.verification
    assert builder.calls == [payload.manifest.document.document_id] * 2


def test_export_refuses_a_non_v3_builder_result(tmp_path: Path) -> None:
    payload = proof_bundle_payload()
    service = ProofBundleExportService(
        bundles=_Builder(payload), archives=LocalArtifactStore(tmp_path / "artifacts")
    )

    with pytest.raises(ProofBundleExportConfigurationError, match="v3"):
        service.export(payload.manifest.document.document_id)


def test_export_refuses_a_builder_that_changes_document_identity(tmp_path: Path) -> None:
    payload = _v3_payload()
    service = ProofBundleExportService(
        bundles=_Builder(payload), archives=LocalArtifactStore(tmp_path / "artifacts")
    )

    with pytest.raises(ProofBundleExportConfigurationError, match="different Document"):
        service.export(UUID("00000000-0000-0000-0000-00000000fe99"))


def test_verify_rejects_invalid_or_missing_handles_without_building(tmp_path: Path) -> None:
    builder = _Builder(_v3_payload())
    service = ProofBundleExportService(
        bundles=builder, archives=LocalArtifactStore(tmp_path / "artifacts")
    )

    for value in (None, "not-a-handle", "bundle:sha256:" + "A" * 64):
        with pytest.raises(ProofBundleHandleError):
            service.verify(value)
    with pytest.raises(RetainedProofBundleNotFoundError):
        service.verify("bundle:sha256:" + "a" * 64)
    assert builder.calls == []


def test_verify_rejects_corrupt_retained_bytes(tmp_path: Path) -> None:
    payload = _v3_payload()
    store = LocalArtifactStore(tmp_path / "artifacts")
    retained = store.put_bytes(b"not a zip", media_type="application/vnd.tarkka.proof-bundle+zip")
    service = ProofBundleExportService(bundles=_Builder(payload), archives=store)

    with pytest.raises(RetainedProofBundleVerificationError, match="ZIP"):
        service.verify("bundle:sha256:" + retained.sha256)


class _InconsistentStore(LocalArtifactStore):
    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        return replace(
            super().put_bytes(
                data,
                original_name=original_name,
                source_uri=source_uri,
                media_type=media_type,
            ),
            media_type="application/zip",
        )


class _StaleSizeStore(LocalArtifactStore):
    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        return replace(
            super().put_bytes(
                data,
                original_name=original_name,
                source_uri=source_uri,
                media_type=media_type,
            ),
            size_bytes=len(data) + 1,
        )


class _ReadOverrideStore(LocalArtifactStore):
    def __init__(self, root: Path, returned: bytes) -> None:
        super().__init__(root)
        self.returned = returned

    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        return self.returned


def test_export_rejects_inconsistent_retained_metadata(tmp_path: Path) -> None:
    payload = _v3_payload()
    service = ProofBundleExportService(
        bundles=_Builder(payload), archives=_InconsistentStore(tmp_path / "artifacts")
    )

    with pytest.raises(ProofBundleExportConfigurationError, match="inconsistent"):
        service.export(payload.manifest.document.document_id)


def test_export_rejects_a_retained_artifact_with_a_stale_byte_count(tmp_path: Path) -> None:
    payload = _v3_payload()
    service = ProofBundleExportService(
        bundles=_Builder(payload), archives=_StaleSizeStore(tmp_path / "artifacts")
    )

    with pytest.raises(ProofBundleExportConfigurationError, match="inconsistent"):
        service.export(payload.manifest.document.document_id)


def test_verify_rejects_empty_or_digest_mismatched_retained_bytes(tmp_path: Path) -> None:
    payload = _v3_payload()
    empty = ProofBundleExportService(
        bundles=_Builder(payload), archives=_ReadOverrideStore(tmp_path / "empty", b"")
    )
    with pytest.raises(RetainedProofBundleVerificationError, match="empty"):
        empty.verify("bundle:sha256:" + "a" * 64)

    archive = build_proof_bundle_bytes(payload)
    mismatch = ProofBundleExportService(
        bundles=_Builder(payload), archives=_ReadOverrideStore(tmp_path / "mismatch", archive)
    )
    with pytest.raises(RetainedProofBundleVerificationError, match="requested handle"):
        mismatch.verify("bundle:sha256:" + "a" * 64)


def test_parse_proof_bundle_handle_returns_only_the_digest() -> None:
    digest = "a" * 64
    assert parse_proof_bundle_handle(f"bundle:sha256:{digest}") == digest
