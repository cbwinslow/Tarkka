from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from tarkka.application.fuzzy_identity import FuzzyIdentityMatcher
from tarkka.application.identity_review import (
    IdentityCandidateNotFoundError,
    IdentityReviewService,
)
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
    external_ids: dict[str, str] | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title=title,
        year=year,
        doi=doi,
        external_ids=external_ids or {},
    )


def _snapshot() -> SearchSnapshot:
    return SearchSnapshot(
        snapshot_id=uuid4(),
        query=ResearchQuery("baseball prediction"),
        providers_used=("openalex", "semantic-scholar"),
        records=(
            _record("openalex", "W1", "Machine Learning for Baseball Win Prediction"),
            _record("semantic-scholar", "S1", "Machine Learning for Baseball Win Prediction"),
        ),
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
    assert candidate.matcher_version == "title-year-v1"
    assert {item.signal for item in candidate.evidence} == {
        "title_similarity",
        "publication_year",
    }


def test_unicode_compatibility_forms_normalize_to_same_title() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "ＭＡＣＨＩＮＥ ＬＥＡＲＮＩＮＧ ＦＯＲ ＢＡＳＥＢＡＬＬ"),
        _record("semantic-scholar", "S1", "machine learning for baseball"),
    )

    assert candidate is not None
    assert candidate.confidence == 1.0


def test_non_latin_titles_are_not_discarded() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "棒球比赛结果预测"),
        _record("semantic-scholar", "S1", "棒球比赛结果预测"),
    )

    assert candidate is not None
    assert candidate.confidence == 1.0


def test_conflicting_strong_identifiers_never_become_fuzzy_candidates() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "Same title", doi="10.1234/one"),
        _record("crossref", "C1", "Same title", doi="10.1234/two"),
    )

    assert candidate is None


def test_conflicting_arxiv_identifiers_never_become_fuzzy_candidates() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "Same title", external_ids={"arxiv": "2401.00001"}),
        _record("semantic-scholar", "S1", "Same title", external_ids={"arxiv": "2401.00002"}),
    )

    assert candidate is None


def test_years_more_than_one_apart_are_rejected() -> None:
    matcher = FuzzyIdentityMatcher()
    candidate = matcher.compare(
        _record("openalex", "W1", "Exact Same Research Title", year=2020),
        _record("semantic-scholar", "S1", "Exact Same Research Title", year=2023),
    )

    assert candidate is None


def test_titles_that_normalize_to_empty_are_rejected() -> None:
    matcher = FuzzyIdentityMatcher()

    assert matcher.compare(
        _record("openalex", "W1", "---"),
        _record("semantic-scholar", "S1", "..."),
    ) is None


def test_suggestions_include_actionable_snapshot_indexes(tmp_path: Path) -> None:
    snapshot = _snapshot()
    service = IdentityReviewService(
        snapshots=_Snapshots(snapshot),
        decisions=JsonlIdentityDecisionLog(tmp_path / "identity_decisions.jsonl"),
    )

    candidate = service.suggest(snapshot.snapshot_id)[0]

    assert candidate.left_index == 0
    assert candidate.right_index == 1
    decision = service.decide(
        snapshot.snapshot_id,
        candidate.left_index,
        candidate.right_index,
        IdentityDecision.ACCEPT,
    )
    assert decision.candidate_id == candidate.candidate_id


def test_accept_records_auditable_decision_without_merging(tmp_path: Path) -> None:
    snapshot = _snapshot()
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
    assert payload["matcher_version"] == "title-year-v1"
    assert payload["confidence"] == 1.0
    assert {item["signal"] for item in payload["evidence"]} == {
        "title_similarity",
        "publication_year",
    }


def test_negative_identity_indexes_are_rejected_before_lookup(tmp_path: Path) -> None:
    snapshot = _snapshot()
    service = IdentityReviewService(
        snapshots=_Snapshots(snapshot),
        decisions=JsonlIdentityDecisionLog(tmp_path / "identity_decisions.jsonl"),
    )

    with pytest.raises(IdentityCandidateNotFoundError, match="non-negative"):
        service.decide(snapshot.snapshot_id, -1, 0, IdentityDecision.REJECT)
