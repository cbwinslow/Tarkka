from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.citations import WorkRelation, WorkRelationKind
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.json_citation_repository import (
    CitationConflictError,
    JsonCitationRepository,
)


def _relation() -> WorkRelation:
    return WorkRelation(
        relation_id=uuid4(),
        subject_work_id=uuid4(),
        object_work_id=uuid4(),
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=uuid4(),
        source_reference_id=uuid4(),
    )


def test_get_or_create_relation_reuses_first_persisted_event(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    first = _relation()
    later_equivalent = replace(first, created_at=first.created_at + timedelta(seconds=1))

    assert repository.get_or_create_relation(first) == first
    assert repository.get_or_create_relation(later_equivalent) == first
    assert repository.get_relation(first.relation_id) == first


def test_get_or_create_relation_rejects_provenance_conflict(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    first = _relation()
    repository.get_or_create_relation(first)

    with pytest.raises(CitationConflictError, match="conflicting relation"):
        repository.get_or_create_relation(
            replace(first, source_document_id=uuid4())
        )
