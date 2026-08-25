from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.migrations import upgrade
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.source_observation_repository import (
    PostgresSourceObservationRepository,
)
from tests.contracts.source_observation_repository import SourceObservationRepositoryContract

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000b201")
_OBSERVATION_ID = UUID("00000000-0000-0000-0000-00000000b202")
_LINK_ID = UUID("00000000-0000-0000-0000-00000000b203")
_OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="d" * 64,
        size_bytes=12,
        media_type="application/xml",
        storage_key=PurePosixPath("artifacts/dd/article.xml"),
        acquired_at=_OBSERVED_AT,
    )


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=_OBSERVATION_ID,
        source_name="fixture",
        source_version="1",
        basis=ObservationBasis.NATIVE,
        native_artifact_id=_ARTIFACT_ID,
        metadata={
            "title": "Evidence first",
            "native": {"identifiers": ["pmcid:PMC123456"]},
        },
        observed_at=_OBSERVED_AT,
    )


def _link() -> ResourceLinkObservation:
    return ResourceLinkObservation(
        link_id=_LINK_ID,
        observation_id=_OBSERVATION_ID,
        target_uri="https://example.test/supplement.csv",
        relation=ResourceRelation.SUPPLEMENT,
        media_type="text/csv",
        label="Supplement",
        metadata={"native": {"targets": ["table-1", "figure-2"]}},
    )


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations() -> None:
    upgrade(_settings())


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


@pytest.fixture
def repository() -> PostgresSourceObservationRepository:
    PostgresResearchRepository(_settings()).save_artifact(_artifact())
    return PostgresSourceObservationRepository(_settings())


def test_postgres_source_observation_repository_satisfies_shared_contract(
    repository: PostgresSourceObservationRepository,
) -> None:
    observation = _observation()
    link = _link()
    SourceObservationRepositoryContract.assert_missing_reads_are_empty(repository, observation)
    SourceObservationRepositoryContract.assert_first_seen_is_idempotent(
        repository, observation, replace(observation, observed_at=_OBSERVED_AT + timedelta(days=1))
    )
    SourceObservationRepositoryContract.assert_link_write_is_idempotent(
        repository, observation, link
    )


def test_postgres_source_observation_repository_limits_links_to_artifact(
    repository: PostgresSourceObservationRepository,
) -> None:
    observation = _observation()
    repository.save_observation(observation)
    repository.save_resource_link(_link())

    assert repository.list_observations_for_artifact(_ARTIFACT_ID) == (observation,)
    assert repository.page_resource_links_for_artifact(_ARTIFACT_ID, offset=0, limit=1) == (
        1,
        (_link(),),
    )
    assert repository.get_resource_link_for_artifact(_ARTIFACT_ID, _LINK_ID) == _link()
