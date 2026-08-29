"""Repeatable-read PostgreSQL snapshots for proof-bundle creation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from tarkka.application.proof_bundles import (
    ProofBundleArtifactNotFoundError,
    ProofBundleSnapshot,
)
from tarkka.infrastructure.postgres.connection import (
    PostgresSettings,
    connect,
    translate_driver_error,
)
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.source_observation_repository import (
    PostgresSourceObservationRepository,
)

ConnectionFactory = Callable[[PostgresSettings], Any]


class PostgresProofBundleSnapshotReader:
    """Read bundle state through one read-only REPEATABLE READ transaction."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connection_factory: ConnectionFactory = connect,
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def read(self, document_id: UUID) -> ProofBundleSnapshot | None:
        try:
            connection = self._connect(self._settings)
            try:
                with connection:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    document = PostgresResearchRepository._get_document(connection, document_id)
                    if document is None:
                        return None
                    artifact = PostgresResearchRepository._get_artifact(
                        connection, document.artifact_id
                    )
                    if artifact is None:
                        raise ProofBundleArtifactNotFoundError(
                            "artifact not found for document "
                            f"{document_id}: {document.artifact_id}"
                        )
                    observations = (
                        PostgresSourceObservationRepository._list_observations_for_artifact(
                            connection, artifact.artifact_id
                        )
                    )
                    resource_links = tuple(
                        link
                        for observation in observations
                        for link in PostgresSourceObservationRepository._list_resource_links(
                            connection, observation.observation_id
                        )
                    )
                    # Work↔Document links are currently a local-JSON persistence capability;
                    # PostgreSQL bundle snapshots must not silently mix in stale JSON state.
                    return ProofBundleSnapshot(
                        document=document,
                        artifact=artifact,
                        source_observations=observations,
                        resource_links=resource_links,
                    )
            finally:
                connection.close()
        except Exception as exc:
            translated = translate_driver_error(exc)
            if translated is not None:
                raise translated from exc
            raise
