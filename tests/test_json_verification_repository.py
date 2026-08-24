from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.storage.json_verification_repository import (
    JsonVerificationRepository,
    VerificationConflictError,
)


def _relation() -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=uuid4(),
        claim_id=uuid4(),
        evidence_id=uuid4(),
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="fixture-verifier",
        verifier_version="1",
        confidence=0.8,
    )


def test_json_verification_repository_round_trips_idempotently_and_pages(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    first = _relation()
    second = _relation()
    second = replace(second, claim_id=first.claim_id)

    repository.save_relation(first)
    repository.save_relation(first)
    repository.save_relation(second)

    reopened = JsonVerificationRepository(tmp_path / "verifications.json")
    assert reopened.get_relation(first.relation_id) == first
    assert reopened.count_relations(first.claim_id) == 2
    assert len(reopened.list_relations(first.claim_id, offset=1, limit=1)) == 1


def test_json_verification_repository_rejects_conflicting_stable_identity(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    relation = _relation()
    repository.save_relation(relation)

    with pytest.raises(VerificationConflictError, match="conflicting evidence relation"):
        repository.save_relation(replace(relation, confidence=0.3))


def test_open_existing_does_not_initialize_missing_verification_catalog(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "verifications.json"

    assert JsonVerificationRepository.open_existing(path) is None
    assert not path.parent.exists()


def test_verification_catalog_rejects_corruption_without_repairing_it(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    future_catalog = {"schema_version": 2, "relations": {}}
    repository.path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid or unsupported verification catalog"):
        repository.get_relation(uuid4())

    assert json.loads(repository.path.read_text(encoding="utf-8")) == future_catalog


def test_verification_catalog_rejects_relation_identity_mismatch(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    relation = _relation()
    catalog = {
        "schema_version": 1,
        "relations": {str(uuid4()): {
            "relation_id": str(relation.relation_id),
            "claim_id": str(relation.claim_id),
            "kind": relation.kind.value,
            "verifier_name": relation.verifier_name,
            "verifier_version": relation.verifier_version,
            "confidence": relation.confidence,
            "human_review_state": relation.human_review_state.value,
            "evidence_id": str(relation.evidence_id),
            "citation_context_id": None,
            "reasoning_summary": None,
            "created_at": relation.created_at.isoformat(),
        }},
    }
    repository.path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="relation_id does not match catalog key"):
        repository.get_relation(relation.relation_id)
