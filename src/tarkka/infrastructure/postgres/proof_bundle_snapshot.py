"""Repeatable-read PostgreSQL snapshots for proof-bundle creation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.document_research_state import (
    DEFAULT_DOCUMENT_RESEARCH_STATE_LIMITS,
    DocumentResearchStateLimits,
    assemble_document_research_state,
)
from tarkka.application.proof_bundles import (
    ProofBundleArtifactNotFoundError,
    ProofBundleSnapshot,
    ProofBundleV2Snapshot,
)
from tarkka.infrastructure.postgres.claim_lineage_readers import (
    PostgresClaimLineageCitationReader,
    PostgresClaimLineageDocumentReader,
    PostgresClaimLineageRelationReader,
    PostgresClaimLineageSourceReader,
)
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)
from tarkka.infrastructure.postgres.research_repository import (
    get_artifact_with_connection,
    get_document_with_connection,
)
from tarkka.infrastructure.postgres.source_observation_repository import (
    list_observations_for_artifact_with_connection,
    list_resource_links_with_connection,
)
from tarkka.infrastructure.postgres.work_document_repository import (
    list_document_work_links_with_connection,
)


class PostgresProofBundleSnapshotReader:
    """Read bundle v1 state through one read-only REPEATABLE READ transaction."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connection_factory: ConnectionFactory = connect,
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def read(self, document_id: UUID) -> ProofBundleSnapshot | None:
        return self._read_transaction(document_id)

    def _read_transaction(self, document_id: UUID) -> ProofBundleSnapshot | None:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return _read_source_snapshot(connection, document_id)


class PostgresProofBundleV2SnapshotReader:
    """Freeze source and complete Claim lineage in one read-only repeatable-read transaction."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connection_factory: ConnectionFactory = connect,
        limits: DocumentResearchStateLimits = DEFAULT_DOCUMENT_RESEARCH_STATE_LIMITS,
    ) -> None:
        self._settings = settings
        self._connect = connection_factory
        self._limits = limits

    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            source = _read_source_snapshot(connection, document_id)
            if source is None:
                return None
            extraction_reader = PostgresClaimLineageSourceReader(connection)
            claims = extraction_reader.list_claims(
                document_id,
                limit=self._limits.max_claims + 1,
            )
            research_state = assemble_document_research_state(
                document_id,
                claims,
                ClaimLineageService(
                    source=extraction_reader,
                    relations=PostgresClaimLineageRelationReader(connection),
                    documents=PostgresClaimLineageDocumentReader(connection),
                    citations=PostgresClaimLineageCitationReader(connection),
                ),
                limits=self._limits,
            )
            return ProofBundleV2Snapshot(
                source=source,
                research_state=research_state,
            )


def _read_source_snapshot(connection: Any, document_id: UUID) -> ProofBundleSnapshot | None:
    document = get_document_with_connection(connection, document_id)
    if document is None:
        return None
    artifact = get_artifact_with_connection(connection, document.artifact_id)
    if artifact is None:
        raise ProofBundleArtifactNotFoundError(
            f"artifact not found for document {document_id}: {document.artifact_id}"
        )
    work_documents = list_document_work_links_with_connection(connection, document_id)
    observations = list_observations_for_artifact_with_connection(
        connection,
        artifact.artifact_id,
    )
    resource_links = tuple(
        link
        for observation in observations
        for link in list_resource_links_with_connection(
            connection,
            observation.observation_id,
        )
    )
    return ProofBundleSnapshot(
        document=document,
        artifact=artifact,
        work_documents=work_documents,
        source_observations=observations,
        resource_links=resource_links,
    )
