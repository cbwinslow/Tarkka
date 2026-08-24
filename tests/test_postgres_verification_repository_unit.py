from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from tarkka.domain.extraction import HumanReviewState
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.postgres.verification_repository import _from_row, _identity


def test_postgres_verification_row_round_trips_domain_fields() -> None:
    relation = _from_row(
        (
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
            "supports",
            "human-review",
            "1",
            0.9,
            "verified",
            UUID("00000000-0000-0000-0000-000000000003"),
            None,
            "Exact span supports the claim.",
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    assert relation == EvidenceRelation(
        relation_id=UUID("00000000-0000-0000-0000-000000000001"),
        claim_id=UUID("00000000-0000-0000-0000-000000000002"),
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.9,
        human_review_state=HumanReviewState.VERIFIED,
        evidence_id=UUID("00000000-0000-0000-0000-000000000003"),
        reasoning_summary="Exact span supports the claim.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_verification_identity_excludes_created_timestamp_only() -> None:
    base = EvidenceRelation(
        relation_id=UUID("00000000-0000-0000-0000-000000000001"),
        claim_id=UUID("00000000-0000-0000-0000-000000000002"),
        kind=EvidenceRelationKind.NO_EVIDENCE,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.9,
    )
    changed = replace(base, confidence=0.1)

    assert _identity(base) != _identity(changed)
