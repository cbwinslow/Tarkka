"""Shared runtime composition for proof-bundle application services."""

from __future__ import annotations

import os
from pathlib import Path

from tarkka.application.proof_bundles import (
    ProofBundleService,
    ProofBundleSnapshotReader,
    ProofBundleV2Service,
    ProofBundleV2SnapshotReader,
    ProofBundleV3Service,
)
from tarkka.config import document_backend
from tarkka.domain.proof_bundle_v2 import PROOF_BUNDLE_SCHEMA_VERSION_V2
from tarkka.domain.proof_bundle_v3 import PROOF_BUNDLE_SCHEMA_VERSION_V3
from tarkka.domain.proof_bundles import PROOF_BUNDLE_SCHEMA_VERSION
from tarkka.infrastructure.normalized_document_json import canonical_normalized_document_bytes
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import (
    PostgresProofBundleSnapshotReader,
    PostgresProofBundleV2SnapshotReader,
)
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.proof_bundle_snapshot import (
    JsonProofBundleSnapshotReader,
    JsonProofBundleV2SnapshotReader,
)

SUPPORTED_PROOF_BUNDLE_SCHEMA_VERSIONS = (
    PROOF_BUNDLE_SCHEMA_VERSION,
    PROOF_BUNDLE_SCHEMA_VERSION_V2,
    PROOF_BUNDLE_SCHEMA_VERSION_V3,
)


def tarkka_home() -> Path:
    """Return the configured Tarkka home used by local durable adapters."""
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def proof_bundle_service(
    schema_version: int = PROOF_BUNDLE_SCHEMA_VERSION,
) -> ProofBundleService | ProofBundleV2Service | ProofBundleV3Service:
    """Compose one proof-bundle service over the configured durable backend."""
    if schema_version not in SUPPORTED_PROOF_BUNDLE_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported proof bundle schema version: {schema_version}")

    home = tarkka_home()
    if schema_version == PROOF_BUNDLE_SCHEMA_VERSION:
        snapshots: ProofBundleSnapshotReader
        if document_backend() == "json":
            documents = JsonResearchRepository(home / "catalog.json")
            observations = JsonSourceObservationRepository.open_existing(
                home / "source_observations.json"
            )
            snapshots = JsonProofBundleSnapshotReader(
                documents=documents,
                observations=observations,
            )
        else:
            snapshots = PostgresProofBundleSnapshotReader(PostgresSettings.from_environment())
        return ProofBundleService(
            snapshots=snapshots,
            artifacts=LocalArtifactStore(home / "artifacts"),
        )

    v2_snapshots: ProofBundleV2SnapshotReader
    if document_backend() == "json":
        documents = JsonResearchRepository(home / "catalog.json")
        v2_snapshots = JsonProofBundleV2SnapshotReader(
            documents=documents,
            observations_path=home / "source_observations.json",
            extractions_path=home / "extractions.json",
            verifications_path=home / "verifications.json",
            citations_path=home / "citations.json",
        )
    else:
        v2_snapshots = PostgresProofBundleV2SnapshotReader(PostgresSettings.from_environment())
    artifacts = LocalArtifactStore(home / "artifacts")
    if schema_version == PROOF_BUNDLE_SCHEMA_VERSION_V2:
        return ProofBundleV2Service(
            snapshots=v2_snapshots,
            artifacts=artifacts,
            encode_research_state=canonical_research_state_bytes,
        )
    return ProofBundleV3Service(
        snapshots=v2_snapshots,
        artifacts=artifacts,
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    )


def proof_bundle_v3_service() -> ProofBundleV3Service:
    """Compose the configured v3 builder without exposing a schema-version union to callers."""
    service = proof_bundle_service(PROOF_BUNDLE_SCHEMA_VERSION_V3)
    if not isinstance(service, ProofBundleV3Service):
        raise RuntimeError("proof-bundle v3 runtime composition returned the wrong service")
    return service
