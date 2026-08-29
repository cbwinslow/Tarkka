from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.fuzzy_identity import FuzzyIdentityMatcher
from tarkka.application.identity import CanonicalWorkCandidate
from tarkka.application.work_selection import SnapshotRecordNotFoundError, WorkSelectionService
from tarkka.application.works import WorkCatalogService, WorkIdentityConflictError
from tarkka.domain.discovery import DiscoveryRecord, SearchSnapshot
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.ports.snapshots import SearchSnapshotReader
from tarkka.ports.works import WorkRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _record(
    provider: str,
    provider_id: str,
    *,
    year: int | None = 2024,
    doi: str | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title="A shared research title",
        year=year,
        doi=doi,
    )


def test_fuzzy_identity_handles_missing_year_and_conflicting_valid_dois() -> None:
    matcher = FuzzyIdentityMatcher(minimum_confidence=0.0)

    no_year_candidate = matcher.compare(
        _record("openalex", "W1", year=None),
        _record("crossref", "C1", year=2024),
    )
    assert no_year_candidate is not None
    assert len(no_year_candidate.evidence) == 1

    assert matcher.compare(
        _record("crossref", "C2", doi="10.1038/nphys1170"),
        _record("openalex", "W2", doi="10.1038/nature12373"),
    ) is None


class _ExplodingSnapshots:
    def get(self, snapshot_id: UUID) -> SearchSnapshot | None:
        raise AssertionError(f"snapshot lookup must not occur for negative index: {snapshot_id}")


class _ExplodingCatalog:
    def persist_candidate(self, candidate: CanonicalWorkCandidate) -> Work:
        del candidate
        raise AssertionError("catalog must not be called for negative index")


def test_work_selection_rejects_negative_index_before_snapshot_lookup() -> None:
    service = WorkSelectionService(
        cast(SearchSnapshotReader, _ExplodingSnapshots()),
        cast(WorkCatalogService, _ExplodingCatalog()),
    )

    with pytest.raises(SnapshotRecordNotFoundError, match="non-negative"):
        service.save_snapshot_result(uuid4(), -1)


class _RacingAliasRepository:
    def __init__(self, conflicting_work: Work) -> None:
        self.conflicting_work = conflicting_work
        self.lookup_count = 0
        self.works: dict[UUID, Work] = {}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def save_work(self, work: Work) -> None:
        self.works[work.work_id] = work

    def get_work(self, work_id: UUID) -> Work | None:
        return self.works.get(work_id)

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        assert (scheme, value) == ("custom", "shared-id")
        self.lookup_count += 1
        return None if self.lookup_count == 1 else self.conflicting_work

    def save_identifier(self, identifier: WorkIdentifier) -> None:
        raise AssertionError(f"conflicting alias must not be saved: {identifier}")

    def list_identifiers(self, work_id: UUID) -> tuple[WorkIdentifier, ...]:
        del work_id
        return ()

    def save_source_record(self, source_record: WorkSourceRecord) -> None:
        raise AssertionError(f"source record must not be saved after alias conflict: {source_record}")

    def list_source_records(self, work_id: UUID) -> tuple[WorkSourceRecord, ...]:
        del work_id
        return ()


def test_work_catalog_fails_closed_on_alias_race() -> None:
    conflicting_work = Work(work_id=uuid4(), title="Concurrent work")
    repository = _RacingAliasRepository(conflicting_work)
    catalog = WorkCatalogService(cast(WorkRepository, repository))
    candidate = CanonicalWorkCandidate(
        canonical_key="provider:custom:shared-id",
        title="Candidate work",
        year=2024,
        doi=None,
        records=(
            DiscoveryRecord(
                provider="custom",
                provider_id="shared-id",
                title="Candidate work",
                year=2024,
            ),
        ),
    )

    with pytest.raises(WorkIdentityConflictError, match="already belongs to work"):
        catalog.persist_candidate(candidate)
    assert repository.lookup_count == 2
