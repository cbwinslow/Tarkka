from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.fuzzy_identity import FuzzyIdentityMatcher
from tarkka.application.identity import CanonicalWorkCandidate
from tarkka.application.identity_review import (
    IdentityCandidateNotFoundError,
    IdentityReviewService,
    IdentitySnapshotNotFoundError,
)
from tarkka.application.work_selection import (
    SnapshotNotFoundError,
    WorkSelectionService,
)
from tarkka.application.works import (
    WorkCatalogService,
    WorkEnrichmentError,
    WorkNotFoundError,
)
from tarkka.domain.discovery import DiscoveryRecord, ResearchQuery, SearchSnapshot
from tarkka.domain.identity_candidates import IdentityDecision, IdentityDecisionRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.ports.identity_decisions import IdentityDecisionRecorder
from tarkka.ports.snapshots import SearchSnapshotReader
from tarkka.ports.works import WorkMetadataEnricher, WorkRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _record(
    provider: str,
    provider_id: str,
    title: str = "A shared research title",
    *,
    year: int | None = 2024,
    doi: str | None = None,
    external_ids: dict[str, str] | None = None,
    metadata: dict[str, object] | None = None,
    abstract: str | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title=title,
        year=year,
        doi=doi,
        external_ids=external_ids or {},
        metadata=metadata or {},
        abstract=abstract,
    )


def _snapshot(*records: DiscoveryRecord) -> SearchSnapshot:
    return SearchSnapshot(
        snapshot_id=uuid4(),
        query=ResearchQuery(text="identity fixture"),
        providers_used=tuple(dict.fromkeys(record.provider for record in records)),
        records=tuple(records),
    )


@pytest.mark.parametrize("minimum_confidence", [-0.01, 1.01])
def test_fuzzy_identity_rejects_out_of_range_confidence(
    minimum_confidence: float,
) -> None:
    with pytest.raises(ValueError, match="minimum confidence"):
        FuzzyIdentityMatcher(minimum_confidence=minimum_confidence)


def test_fuzzy_identity_rejects_same_provider_blank_normalized_title_and_low_score() -> None:
    matcher = FuzzyIdentityMatcher(minimum_confidence=0.99)

    assert matcher.compare(_record("a", "1"), _record("a", "2")) is None
    assert matcher.compare(
        _record("a", "1", title="---"),
        _record("b", "2", title="Research"),
    ) is None
    assert matcher.compare(
        _record("a", "1", title="Alpha beta"),
        _record("b", "2", title="Completely different work"),
    ) is None


def test_fuzzy_identity_rejects_far_years_and_scores_near_years() -> None:
    matcher = FuzzyIdentityMatcher(minimum_confidence=0.0)
    left = _record("a", "1", year=2024)

    assert matcher.compare(left, _record("b", "2", year=2022)) is None

    same_year = matcher.compare(left, _record("b", "3", year=2024))
    adjacent_year = matcher.compare(left, _record("c", "4", year=2023))

    assert same_year is not None
    assert adjacent_year is not None
    assert same_year.evidence[-1].score == 1.0
    assert adjacent_year.evidence[-1].score == 0.5


def test_fuzzy_identity_strong_doi_and_arxiv_relations_skip_fuzzy_candidates() -> None:
    matcher = FuzzyIdentityMatcher(minimum_confidence=0.0)

    assert matcher.compare(
        _record("crossref", "1", doi="10.1000/alpha"),
        _record("openalex", "2", doi="10.1000/beta"),
    ) is None

    assert matcher.compare(
        _record("arxiv", "2401.00001"),
        _record("openalex", "W1", external_ids={"ARXIV": "2401.00002"}),
    ) is None

    assert matcher.compare(
        _record("arxiv", "not-an-arxiv-id", external_ids={"arXiv": "2401.00001"}),
        _record("semantic_scholar", "S1", external_ids={"arxiv": "2401.00001"}),
    ) is None


@dataclass
class _Snapshots:
    snapshots: dict[UUID, SearchSnapshot] = field(default_factory=dict)

    def get(self, snapshot_id: UUID) -> SearchSnapshot | None:
        return self.snapshots.get(snapshot_id)


@dataclass
class _Decisions:
    records: list[IdentityDecisionRecord] = field(default_factory=list)

    def record(self, record: IdentityDecisionRecord) -> None:
        self.records.append(record)


def _review_service(*snapshots: SearchSnapshot) -> IdentityReviewService:
    reader = _Snapshots({snapshot.snapshot_id: snapshot for snapshot in snapshots})
    return IdentityReviewService(
        snapshots=cast(SearchSnapshotReader, reader),
        decisions=cast(IdentityDecisionRecorder, _Decisions()),
        matcher=FuzzyIdentityMatcher(minimum_confidence=0.0),
    )


def test_identity_review_reports_missing_snapshots() -> None:
    service = _review_service()
    snapshot_id = uuid4()

    with pytest.raises(IdentitySnapshotNotFoundError, match="snapshot not found"):
        service.suggest(snapshot_id)
    with pytest.raises(IdentitySnapshotNotFoundError, match="snapshot not found"):
        service.decide(snapshot_id, 0, 1, IdentityDecision.ACCEPT)


@pytest.mark.parametrize("left_index,right_index", [(-1, 0), (0, -1), (0, 0)])
def test_identity_review_rejects_invalid_candidate_indexes(
    left_index: int,
    right_index: int,
) -> None:
    snapshot = _snapshot(_record("a", "1"), _record("b", "2"))
    service = _review_service(snapshot)

    with pytest.raises(IdentityCandidateNotFoundError, match="different non-negative"):
        service.decide(
            snapshot.snapshot_id,
            left_index,
            right_index,
            IdentityDecision.REJECT,
        )


def test_identity_review_rejects_out_of_range_and_non_candidate_pairs() -> None:
    snapshot = _snapshot(_record("same", "1"), _record("same", "2"))
    service = _review_service(snapshot)

    with pytest.raises(IdentityCandidateNotFoundError, match="out of range"):
        service.decide(snapshot.snapshot_id, 0, 2, IdentityDecision.REJECT)
    with pytest.raises(IdentityCandidateNotFoundError, match="not a fuzzy identity candidate"):
        service.decide(snapshot.snapshot_id, 0, 1, IdentityDecision.REJECT)


class _NeverCatalog:
    def persist_candidate(self, candidate: CanonicalWorkCandidate) -> Work:
        del candidate
        raise AssertionError("catalog must not be called for a missing snapshot")


def test_work_selection_reports_missing_snapshot_before_catalog_access() -> None:
    service = WorkSelectionService(
        cast(SearchSnapshotReader, _Snapshots()),
        cast(WorkCatalogService, _NeverCatalog()),
    )

    with pytest.raises(SnapshotNotFoundError, match="search snapshot not found"):
        service.save_snapshot_result(uuid4(), 0)


@dataclass
class _WorkRepository:
    works: dict[UUID, Work] = field(default_factory=dict)
    identifiers: dict[tuple[str, str], Work] = field(default_factory=dict)
    identifiers_by_work: dict[UUID, list[WorkIdentifier]] = field(default_factory=dict)
    source_records: list[WorkSourceRecord] = field(default_factory=list)
    get_sequence: list[Work | None] = field(default_factory=list)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def save_work(self, work: Work) -> None:
        self.works[work.work_id] = work

    def get_work(self, work_id: UUID) -> Work | None:
        if self.get_sequence:
            return self.get_sequence.pop(0)
        return self.works.get(work_id)

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        return self.identifiers.get((scheme, value))

    def save_identifier(self, identifier: WorkIdentifier) -> None:
        work = self.works[identifier.work_id]
        self.identifiers[(identifier.scheme, identifier.value)] = work
        self.identifiers_by_work.setdefault(identifier.work_id, []).append(identifier)

    def list_identifiers(self, work_id: UUID) -> tuple[WorkIdentifier, ...]:
        return tuple(self.identifiers_by_work.get(work_id, ()))

    def save_source_record(self, source_record: WorkSourceRecord) -> None:
        self.source_records.append(source_record)

    def list_source_records(self, work_id: UUID) -> tuple[WorkSourceRecord, ...]:
        return tuple(
            source_record
            for source_record in self.source_records
            if source_record.work_id == work_id
        )


@dataclass
class _Enricher:
    record: DiscoveryRecord
    name: str = "fixture"
    requested_dois: list[str] = field(default_factory=list)

    def lookup_by_doi(self, doi: str) -> DiscoveryRecord:
        self.requested_dois.append(doi)
        return self.record


def _catalog(repository: _WorkRepository) -> WorkCatalogService:
    return WorkCatalogService(cast(WorkRepository, repository))


def _repository_with_work(*, with_doi: bool = False) -> tuple[_WorkRepository, Work]:
    work = Work(work_id=uuid4(), title="Existing work")
    repository = _WorkRepository(works={work.work_id: work})
    if with_doi:
        identifier = WorkIdentifier(
            identifier_id=uuid4(),
            work_id=work.work_id,
            scheme="doi",
            value="10.1000/existing",
        )
        repository.save_identifier(identifier)
    return repository, work


def test_work_catalog_empty_batch_and_missing_enrichment_work() -> None:
    repository = _WorkRepository()
    catalog = _catalog(repository)

    assert catalog.persist_candidates(()) == ()
    enricher = _Enricher(_record("crossref", "x", doi="10.1000/existing"))
    with pytest.raises(WorkNotFoundError, match="work not found"):
        catalog.enrich_by_doi(uuid4(), cast(WorkMetadataEnricher, enricher))


def test_work_catalog_enrichment_requires_doi_and_matching_provider_doi() -> None:
    repository, work = _repository_with_work()
    catalog = _catalog(repository)
    enricher = _Enricher(_record("crossref", "x", doi="10.1000/other"))

    with pytest.raises(WorkEnrichmentError, match="has no DOI alias"):
        catalog.enrich_by_doi(work.work_id, cast(WorkMetadataEnricher, enricher))

    repository, work = _repository_with_work(with_doi=True)
    catalog = _catalog(repository)
    mismatch = _Enricher(_record("crossref", "x", doi="10.1000/other"))
    with pytest.raises(WorkEnrichmentError, match="returned DOI"):
        catalog.enrich_by_doi(work.work_id, cast(WorkMetadataEnricher, mismatch))
    assert mismatch.requested_dois == ["10.1000/existing"]


def test_work_catalog_detects_work_removed_during_enrichment() -> None:
    repository, work = _repository_with_work(with_doi=True)
    repository.get_sequence = [work, None]
    catalog = _catalog(repository)
    enricher = _Enricher(_record("crossref", "x", doi="10.1000/existing"))

    with pytest.raises(WorkNotFoundError, match="during enrichment"):
        catalog.enrich_by_doi(work.work_id, cast(WorkMetadataEnricher, enricher))


def test_work_catalog_normalizes_aliases_through_public_persistence() -> None:
    repository = _WorkRepository()
    catalog = _catalog(repository)
    records = (
        _record(
            "doi",
            "not-a-doi",
            external_ids={"": "ignored", "doi": "   ", "arxiv": "2401.00001"},
        ),
        _record(
            "custom",
            "canonical-id",
            external_ids={"doi": "10.1000/ABC"},
        ),
    )
    candidate = CanonicalWorkCandidate(
        canonical_key="fixture:aliases",
        title="Alias fixture",
        year=2024,
        doi="not-a-doi",
        records=records,
    )

    work = catalog.persist_candidate(candidate)
    aliases = {
        (identifier.scheme, identifier.value)
        for identifier in repository.list_identifiers(work.work_id)
    }

    assert ("doi", "10.1000/abc") in aliases
    assert ("arxiv", "2401.00001") in aliases
    assert ("custom", "canonical-id") in aliases
    assert ("doi", "not-a-doi") not in aliases
    assert all(scheme and value for scheme, value in aliases)
