from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pytest

from tarkka.domain.models import Acquisition, Artifact
from tarkka.infrastructure.postgres.acquisition_recorder import PostgresAcquisitionRecorder
from tarkka.infrastructure.postgres.connection import (
    PostgresOperationError,
    PostgresSettings,
    connect,
)
from tarkka.infrastructure.postgres.migrations import upgrade
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000a301")
_ACQUIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="c" * 64,
        size_bytes=42,
        media_type="application/pdf",
        storage_key=PurePosixPath("artifacts/cc/paper.pdf"),
        acquired_at=_ACQUIRED_AT,
    )


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations() -> None:
    upgrade(_settings())


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


def test_postgres_acquisition_recorder_preserves_multiple_origins_per_artifact() -> None:
    artifact = _artifact()
    PostgresResearchRepository(_settings()).save_artifact(artifact)
    recorder = PostgresAcquisitionRecorder(_settings())
    first = Acquisition(
        acquisition_id=uuid4(),
        artifact_id=artifact.artifact_id,
        source_uri="file:///research/paper.pdf",
        original_name="paper.pdf",
        acquired_at=_ACQUIRED_AT,
    )
    second = Acquisition(
        acquisition_id=uuid4(),
        artifact_id=artifact.artifact_id,
        source_uri="https://example.test/paper.pdf",
        original_name="paper.pdf",
        acquired_at=datetime(2026, 1, 2, tzinfo=UTC),
        metadata={"provider": "fixture"},
    )

    recorder.record(first)
    recorder.record(second)
    recorder.record(first)

    with connect(_settings()) as connection:
        rows = connection.execute(
            "SELECT source_uri, metadata FROM tarkka.acquisition ORDER BY acquired_at"
        ).fetchall()
    assert rows == [
        ("file:///research/paper.pdf", {}),
        ("https://example.test/paper.pdf", {"provider": "fixture"}),
    ]


def test_postgres_acquisition_recorder_requires_a_persisted_artifact() -> None:
    acquisition = Acquisition(
        acquisition_id=uuid4(),
        artifact_id=_ARTIFACT_ID,
        source_uri="https://example.test/missing.pdf",
        acquired_at=_ACQUIRED_AT,
    )

    with pytest.raises(PostgresOperationError):
        PostgresAcquisitionRecorder(_settings()).record(acquisition)
