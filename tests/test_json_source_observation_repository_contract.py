from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.storage import json_source_observation_repository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
    SourceObservationConflictError,
)
from tests.contracts.source_observation_repository import (
    SourceObservationRepositoryContract,
)

_OBSERVATION_ID = UUID("00000000-0000-0000-0000-000000000901")
_LINK_ID = UUID("00000000-0000-0000-0000-000000000902")
_FIRST_SEEN = datetime(2026, 1, 1, tzinfo=UTC)


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=_OBSERVATION_ID,
        source_name="fixture",
        source_version="1",
        basis=ObservationBasis.NATIVE,
        provider_record_id="record-1",
        media_type="application/json",
        metadata={"title": "Evidence first", "score": 0.9},
        observed_at=_FIRST_SEEN,
    )


def _link() -> ResourceLinkObservation:
    return ResourceLinkObservation(
        link_id=_LINK_ID,
        observation_id=_OBSERVATION_ID,
        target_uri="https://example.org/supplement.csv",
        relation=ResourceRelation.SUPPLEMENT,
        media_type="text/csv",
        label="Supplementary data",
        metadata={"source_anchor": "supp-1"},
    )


def test_json_source_repository_satisfies_missing_read_contract(tmp_path: Path) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")

    SourceObservationRepositoryContract.assert_missing_reads_are_empty(
        repository,
        _observation(),
    )


def test_json_source_repository_preserves_first_seen_observation(tmp_path: Path) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    first = _observation()
    later = replace(first, observed_at=_FIRST_SEEN + timedelta(days=1))

    SourceObservationRepositoryContract.assert_first_seen_is_idempotent(
        repository,
        first,
        later,
    )


def test_json_source_repository_deduplicates_resource_links(tmp_path: Path) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")

    SourceObservationRepositoryContract.assert_link_write_is_idempotent(
        repository,
        _observation(),
        _link(),
    )


def test_json_source_repository_rejects_stable_id_conflicts(tmp_path: Path) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    first = _observation()
    conflicting = replace(first, metadata={"title": "Different evidence"})

    SourceObservationRepositoryContract.assert_conflicting_observation_fails(
        repository,
        first,
        conflicting,
        SourceObservationConflictError,
    )


def test_json_source_repository_rejects_resource_link_conflicts(tmp_path: Path) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    first = _link()

    SourceObservationRepositoryContract.assert_conflicting_link_fails(
        repository,
        _observation(),
        first,
        replace(first, target_uri="https://example.org/different.csv"),
        SourceObservationConflictError,
    )


def test_json_source_repository_fsyncs_parent_directory_after_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[Path] = []
    monkeypatch.setattr(json_source_observation_repository, "_fsync_directory", flushed.append)

    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    repository.save_observation(_observation())

    assert flushed == [repository.path.parent, repository.path.parent]
