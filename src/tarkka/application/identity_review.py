from __future__ import annotations

from uuid import UUID

from tarkka.application.fuzzy_identity import FuzzyIdentityMatcher
from tarkka.domain.identity_candidates import (
    IdentityCandidate,
    IdentityDecision,
    IdentityDecisionRecord,
)
from tarkka.ports.identity_decisions import IdentityDecisionRecorder
from tarkka.ports.snapshots import SearchSnapshotReader


class IdentitySnapshotNotFoundError(LookupError):
    pass


class IdentityCandidateNotFoundError(LookupError):
    pass


class IdentityReviewService:
    def __init__(
        self,
        *,
        snapshots: SearchSnapshotReader,
        decisions: IdentityDecisionRecorder,
        matcher: FuzzyIdentityMatcher | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._decisions = decisions
        self._matcher = matcher or FuzzyIdentityMatcher()

    def suggest(self, snapshot_id: UUID) -> tuple[IdentityCandidate, ...]:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise IdentitySnapshotNotFoundError(f"snapshot not found: {snapshot_id}")
        return self._matcher.find(snapshot.records)

    def decide(
        self,
        snapshot_id: UUID,
        left_index: int,
        right_index: int,
        decision: IdentityDecision,
        *,
        actor: str = "cli",
        rationale: str | None = None,
    ) -> IdentityDecisionRecord:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise IdentitySnapshotNotFoundError(f"snapshot not found: {snapshot_id}")
        if left_index < 0 or right_index < 0 or left_index == right_index:
            raise IdentityCandidateNotFoundError(
                "identity candidate requires two different non-negative indexes"
            )
        try:
            left = snapshot.records[left_index]
            right = snapshot.records[right_index]
        except IndexError as exc:
            raise IdentityCandidateNotFoundError("identity candidate index out of range") from exc

        candidate = self._matcher.compare(
            left,
            right,
            left_index=left_index,
            right_index=right_index,
        )
        if candidate is None:
            raise IdentityCandidateNotFoundError(
                f"records {left_index} and {right_index} are not a fuzzy identity candidate"
            )
        record = IdentityDecisionRecord(
            candidate_id=candidate.candidate_id,
            decision=decision,
            snapshot_id=snapshot_id,
            left_index=left_index,
            right_index=right_index,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
            matcher_version=candidate.matcher_version,
            actor=actor,
            rationale=rationale,
        )
        self._decisions.record(record)
        return record
