from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.proof_bundles import (
    ProofBundleDocumentNotFoundError,
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
        research_state={
            "format": "tarkka.document-research-state",
            "schema_version": 1,
            "document_id": str(document.document_id),
            "claims": [],
        },
    )


def test_v2_service_builds_deterministic_integrity_bound_payload() -> None:
    service = ProofBundleV2Service(
        snapshots=_SnapshotReader(_snapshot()),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    )

    first = service.build(_DOCUMENT_ID)
    second = service.build(_DOCUMENT_ID)

    assert isinstance(first.manifest, ProofBundleManifestV2)
    assert first == second
    assert first.research_state_bytes == canonical_research_state_bytes(_snapshot().research_state)
    assert first.manifest.research_state.sha256 == hashlib.sha256(
        first.research_state_bytes
    ).hexdigest()
    assert first.manifest.research_state.size_bytes == len(first.research_state_bytes)
    archive = build_proof_bundle_bytes(first)
    verification = verify_proof_bundle_bytes(archive)
    assert verification.document_id == str(_DOCUMENT_ID)
    assert verification.member_count == 3


def test_v2_service_rejects_unknown_document() -> None:
    service = ProofBundleV2Service(
        snapshots=_SnapshotReader(None),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    )

    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        service.build(_DOCUMENT_ID)
