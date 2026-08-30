from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from tarkka.application.proof_bundles import (
    ProofBundleArtifactNotFoundError,
    ProofBundleService,
    ProofBundleSnapshot,
)
from tarkka.domain.models import Document
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fb01")


class _SnapshotReader:
    def __init__(self, snapshot: ProofBundleSnapshot) -> None:
        self.snapshot = snapshot

    def read(self, document_id: UUID) -> ProofBundleSnapshot | None:
        assert document_id == _DOCUMENT_ID
        return self.snapshot


def test_proof_bundle_service_normalizes_missing_artifact_bytes(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"immutable source", original_name="source.txt", media_type="text/plain")
    document = Document(
        document_id=_DOCUMENT_ID,
        artifact_id=artifact.artifact_id,
        title="Missing bytes",
        parser_name="plain-text",
        parser_version="3",
        sections=(),
        normalized_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    service = ProofBundleService(
        snapshots=_SnapshotReader(ProofBundleSnapshot(document=document, artifact=artifact)),
        artifacts=store,
    )
    store.path_for(artifact).unlink()

    with pytest.raises(ProofBundleArtifactNotFoundError, match=str(artifact.artifact_id)) as error:
        service.build(_DOCUMENT_ID)

    assert isinstance(error.value.__cause__, FileNotFoundError)
