from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.document_research_state import (
    DocumentResearchState,
    document_research_state_view,
)
from tarkka.application.proof_bundles import (
    ProofBundleArtifactLimitError,
    ProofBundleBuildLimits,
    ProofBundleDocumentNotFoundError,
    ProofBundleResearchStateIntegrityError,
    ProofBundleSnapshot,
    ProofBundleV2Snapshot,
    ProofBundleV3Service,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.infrastructure.normalized_document_json import canonical_normalized_document_bytes
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    build_proof_bundle_bytes,
    verify_proof_bundle_bytes,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_BYTES = b"fixture"
_SHA256 = hashlib.sha256(_BYTES).hexdigest()
_ARTIFACT_ID = artifact_id_from_sha256(_SHA256)
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fc01")
_CREATED_AT = datetime(2026, 8, 30, tzinfo=UTC)


class _SnapshotReader:
    def __init__(self, snapshot: ProofBundleV2Snapshot | None) -> None:
        self.snapshot = snapshot

    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None:
        del document_id
        return self.snapshot


class _ArtifactStore:
    def read_bytes(self, artifact: Artifact) -> bytes:
        del artifact
        return _BYTES


class _UnreadableArtifactStore:
    def read_bytes(self, artifact: Artifact) -> bytes:
        raise AssertionError(f"Artifact must not be read: {artifact.artifact_id}")


def _snapshot() -> ProofBundleV2Snapshot:
    artifact = Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256=_SHA256,
        size_bytes=len(_BYTES),
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", _SHA256),
        original_name="fixture.txt",
        acquired_at=_CREATED_AT,
        source_uri="https://example.test/fixture.txt",
    )
    document = Document(
        document_id=_DOCUMENT_ID,
        artifact_id=artifact.artifact_id,
        title="Fixture",
        parser_name="plain-text",
        parser_version="2",
        sections=(),
        normalized_at=_CREATED_AT,
    )
    return ProofBundleV2Snapshot(
        source=ProofBundleSnapshot(document=document, artifact=artifact),
        research_state=DocumentResearchState(
            document_id=document.document_id,
            claim_lineages=(),
        ),
    )


def _service(snapshot: ProofBundleV2Snapshot | None) -> ProofBundleV3Service:
    return ProofBundleV3Service(
        snapshots=_SnapshotReader(snapshot),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    )


def test_v3_service_builds_deterministic_integrity_bound_payload() -> None:
    snapshot = _snapshot()
    service = _service(snapshot)

    first = service.build(_DOCUMENT_ID)
    second = service.build(_DOCUMENT_ID)

    assert isinstance(first.manifest, ProofBundleManifestV3)
    assert first == second
    assert first.research_state_bytes == canonical_research_state_bytes(
        document_research_state_view(snapshot.research_state)
    )
    assert first.normalized_document_bytes == canonical_normalized_document_bytes(
        snapshot.source.document
    )
    assert first.manifest.research_state.sha256 == hashlib.sha256(
        first.research_state_bytes
    ).hexdigest()
    assert first.manifest.normalized_document.sha256 == hashlib.sha256(
        first.normalized_document_bytes
    ).hexdigest()
    archive = build_proof_bundle_bytes(first)
    verification = verify_proof_bundle_bytes(archive)
    assert verification.document_id == str(_DOCUMENT_ID)
    assert verification.member_count == 4


def test_v3_streaming_build_matches_manifest_without_reading_artifact_bytes() -> None:
    snapshot = _snapshot()
    service = ProofBundleV3Service(
        snapshots=_SnapshotReader(snapshot),
        artifacts=_UnreadableArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    )

    payload = service.build_streaming(_DOCUMENT_ID)

    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.artifact is snapshot.source.artifact
    assert payload.research_state_bytes == canonical_research_state_bytes(
        document_research_state_view(snapshot.research_state)
    )
    assert payload.normalized_document_bytes == canonical_normalized_document_bytes(
        snapshot.source.document
    )


def test_v3_service_rejects_unknown_document() -> None:
    service = _service(None)
    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        service.build(_DOCUMENT_ID)
    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        service.build_streaming(_DOCUMENT_ID)


def test_v3_service_rejects_research_state_for_another_document() -> None:
    snapshot = _snapshot()
    mismatched = replace(
        snapshot,
        research_state=DocumentResearchState(document_id=UUID(int=999), claim_lineages=()),
    )
    service = _service(mismatched)

    with pytest.raises(ProofBundleResearchStateIntegrityError, match="different Document"):
        service.build(_DOCUMENT_ID)
    with pytest.raises(ProofBundleResearchStateIntegrityError, match="different Document"):
        service.build_streaming(_DOCUMENT_ID)


def test_v3_service_rejects_oversized_artifact_before_reading_bytes() -> None:
    snapshot = _snapshot()
    oversized = replace(
        snapshot,
        source=replace(
            snapshot.source,
            artifact=replace(snapshot.source.artifact, size_bytes=len(_BYTES) + 1),
        ),
    )
    service = ProofBundleV3Service(
        snapshots=_SnapshotReader(oversized),
        artifacts=_UnreadableArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
        limits=ProofBundleBuildLimits(max_artifact_bytes=len(_BYTES)),
    )

    with pytest.raises(ProofBundleArtifactLimitError, match="configured build byte maximum"):
        service.build(_DOCUMENT_ID)
    with pytest.raises(ProofBundleArtifactLimitError, match="configured build byte maximum"):
        service.build_streaming(_DOCUMENT_ID)


def test_proof_bundle_build_limit_reserves_complete_v3_archive_headroom() -> None:
    with pytest.raises(ValueError, match="max_artifact_bytes must be non-negative"):
        ProofBundleBuildLimits(max_artifact_bytes=-1)

    build_limits = ProofBundleBuildLimits()
    verification_limits = ProofBundleVerificationLimits()
    reserved_bytes = verification_limits.max_archive_bytes - build_limits.max_artifact_bytes
    required_member_headroom = (
        verification_limits.max_manifest_bytes
        + verification_limits.max_research_state_bytes
        + verification_limits.max_normalized_document_bytes
    )

    assert build_limits.max_artifact_bytes < verification_limits.max_artifact_bytes
    assert reserved_bytes > required_member_headroom


def test_v3_archive_round_trips_at_exact_complete_archive_boundary() -> None:
    payload = _service(_snapshot()).build(_DOCUMENT_ID)
    archive = build_proof_bundle_bytes(payload)
    assert payload.research_state_bytes is not None
    assert payload.normalized_document_bytes is not None
    limits = ProofBundleVerificationLimits(
        max_archive_bytes=len(archive),
        max_manifest_bytes=ProofBundleVerificationLimits().max_manifest_bytes,
        max_artifact_bytes=len(payload.artifact_bytes),
        max_research_state_bytes=len(payload.research_state_bytes),
        max_normalized_document_bytes=len(payload.normalized_document_bytes),
    )

    verification = verify_proof_bundle_bytes(archive, limits=limits)

    assert verification.member_count == 4
    with pytest.raises(ProofBundleVerificationError, match="archive exceeds"):
        verify_proof_bundle_bytes(
            archive,
            limits=replace(limits, max_archive_bytes=len(archive) - 1),
        )
