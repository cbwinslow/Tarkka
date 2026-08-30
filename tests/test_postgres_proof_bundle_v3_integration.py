from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.proof_bundles import ProofBundleV3Service
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.normalized_document_json import canonical_normalized_document_bytes
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleV2SnapshotReader
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes, verify_proof_bundle_bytes

pytestmark = [pytest.mark.external, pytest.mark.postgres, pytest.mark.integration]

_BYTES = b"postgres-v3-replay-fixture"
_SHA256 = hashlib.sha256(_BYTES).hexdigest()
_ARTIFACT_ID = artifact_id_from_sha256(_SHA256)
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fb01")
_CREATED_AT = datetime(2026, 8, 30, tzinfo=UTC)


class _ArtifactStore:
    def read_bytes(self, artifact: Artifact) -> bytes:
        assert artifact.artifact_id == _ARTIFACT_ID
        return _BYTES


def test_postgres_snapshot_builds_offline_verifiable_v3_bundle() -> None:
    settings = PostgresSettings.from_environment()
    repository = PostgresResearchRepository(settings)
    artifact = Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256=_SHA256,
        size_bytes=len(_BYTES),
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", _SHA256),
        original_name="postgres-v3.txt",
        acquired_at=_CREATED_AT,
    )
    document = Document(
        document_id=_DOCUMENT_ID,
        artifact_id=artifact.artifact_id,
        title="PostgreSQL v3 fixture",
        parser_name="plain-text",
        parser_version="2",
        sections=(),
        normalized_at=_CREATED_AT,
    )
    repository.save_artifact(artifact)
    repository.save_document(document, build_document_manifest(document, artifact))
    service = ProofBundleV3Service(
        snapshots=PostgresProofBundleV2SnapshotReader(settings),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    )

    first = service.build(document.document_id)
    second = service.build(document.document_id)
    archive = build_proof_bundle_bytes(first)
    verification = verify_proof_bundle_bytes(archive)

    assert first == second
    assert verification.document_id == str(document.document_id)
    assert verification.artifact_sha256 == artifact.sha256
    assert verification.member_count == 4
