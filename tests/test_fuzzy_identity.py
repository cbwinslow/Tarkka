from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from tarkka.application.fuzzy_identity import FuzzyIdentityMatcher
from tarkka.application.identity_review import IdentityReviewService
from tarkka.domain.discovery import DiscoveryRecord, ResearchQuery, SearchSnapshot
from tarkka.domain.identity_candidates import IdentityDecision
from tarkka.infrastructure.storage.identity_decision_log import JsonlIdentityDecisionLog


class _Snapshots:
    def __init__(self, snapshot: SearchSnapshot) -> None:
        self.snapshot = snapshot

    def get(self, snapshot_id: UUID) -> SearchSnapshot | None:
        return self.snapshot if snapshot_id == self.snapshot.snapshot_id else None


def _record(
    provider: str,
    provider_id: str,
    title: str,
    year: int | None = 2024,
    doi: str | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title=title,
        year=year,
        doi=doi,
    )


def test_near_identical_cross_provider_titles_become_review_candidates() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "Machine Learning for Baseball Win Prediction"),
        _record("semantic-scholar", "S1", "Machine Learning for Baseball Win Prediction"),
    )

    assert candidate is not None
    assert candidate.review_required is True
    assert candidate.confidence == 1.0
    assert {item.signal for item in candidate.evidence} == {
        "title_similarity",
        "publication_year",
    }


def test_conflicting_strong_identifiers_never_become_fuzzy_candidates() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "Same title", doi="10.1234/one"),
        _record("crossref", "C1", "Same title", doi="10.1234/two"),
    )

    assert candidate is None


def test_years_more_than_one_apart_are_rejected() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "Exact Same Research Title", year=2020),
        _record("semantic-scholar", "S1", "Exact Same Research Title", year=2023),
    )

    assert candidate is None


def test_accept_records_auditable_decision_without_merging(tmp_path: Path) -> None:
    snapshot = SearchSnapshot(
        snapshot_id=uuid4(),
        query=ResearchQuery("baseball prediction"),
        providers_used=("openalex", "semantic-scholar"),
        records=(
            _record("openalex", "W1", "Machine Learning for Baseball Win Prediction"),
            _record("semantic-scholar", "S1", "Machine Learning for Baseball Win Prediction"),
        ),
    )
    path = tmp_path / "identity_decisions.jsonl"
    service = IdentityReviewService(
        snapshots=_Snapshots(snapshot),
        decisions=JsonlIdentityDecisionLog(path),
    )

    candidates_before = service.suggest(snapshot.snapshot_id)
    decision = service.decide(
        snapshot.snapshot_id,
        0,
        1,
        IdentityDecision.ACCEPT,
        rationale="same study after review",
    )
    candidates_after = service.suggest(snapshot.snapshot_id)

    assert decision.candidate_id == candidates_before[0].candidate_id
    assert candidates_after == candidates_before
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert payload["decision"] == "accept"
    assert payload["rationale"] == "same study after review"
