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
    ProofBundleDocumentNotFoundError,
    ProofBundleResearchStateIntegrityError,
    ProofBundleSnapshot,
    ProofBundleV2Service,
    ProofBundleV2Snapshot,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundle_v2 import ProofBundleManifestV2
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes, verify_proof_bundle_bytes

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_BYTES = b"fixture"
_SHA256 = hashlib.sha256(_BYTES).hexdigest()
_ARTIFACT_ID = artifact_id_from_sha256(_SHA256)
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fd01")
_CREATED_AT = datetime(2026, 8, 29, tzinfo=UTC)


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
        raise AssertionError(
            f"streaming build must not read Artifact bytes: {artifact.artifact_id}"
        )


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
        parser_name="fixture",
        parser_version="1",
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


def test_v2_service_builds_deterministic_integrity_bound_payload() -> None:
    snapshot = _snapshot()
    service = ProofBundleV2Service(
        snapshots=_SnapshotReader(snapshot),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    )

    first = service.build(_DOCUMENT_ID)
    second = service.build(_DOCUMENT_ID)

    assert isinstance(first.manifest, ProofBundleManifestV2)
    assert first == second
    expected_state = document_research_state_view(snapshot.research_state)
    assert expected_state["format"] == "tarkka.document-research-state"
    assert expected_state["schema_version"] == 1
    assert first.research_state_bytes == canonical_research_state_bytes(expected_state)
    assert first.manifest.research_state.sha256 == hashlib.sha256(
        first.research_state_bytes
    ).hexdigest()
    assert first.manifest.research_state.size_bytes == len(first.research_state_bytes)
    archive = build_proof_bundle_bytes(first)
    verification = verify_proof_bundle_bytes(archive)
    assert verification.document_id == str(_DOCUMENT_ID)
    assert verification.member_count == 3


def test_v2_streaming_build_matches_manifest_without_reading_artifact_bytes() -> None:
    snapshot = _snapshot()
    service = ProofBundleV2Service(
        snapshots=_SnapshotReader(snapshot),
        artifacts=_UnreadableArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    )

    payload = service.build_streaming(_DOCUMENT_ID)

    assert isinstance(payload.manifest, ProofBundleManifestV2)
    assert payload.artifact is snapshot.source.artifact
    assert payload.research_state_bytes == canonical_research_state_bytes(
        document_research_state_view(snapshot.research_state)
    )


def test_v2_service_rejects_unknown_document() -> None:
    service = ProofBundleV2Service(
        snapshots=_SnapshotReader(None),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    )

    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        service.build(_DOCUMENT_ID)
    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        service.build_streaming(_DOCUMENT_ID)


def test_v2_service_rejects_research_state_for_another_document() -> None:
    snapshot = _snapshot()
    mismatched = replace(
        snapshot,
        research_state=DocumentResearchState(document_id=UUID(int=999), claim_lineages=()),
    )
    service = ProofBundleV2Service(
        snapshots=_SnapshotReader(mismatched),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    )

    with pytest.raises(ProofBundleResearchStateIntegrityError, match="different Document"):
        service.build(_DOCUMENT_ID)
    with pytest.raises(ProofBundleResearchStateIntegrityError, match="different Document"):
        service.build_streaming(_DOCUMENT_ID)
