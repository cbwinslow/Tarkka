from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tarkka.application.citation_traversal import (
    CitationTraversalPolicy,
    CitationTraversalService,
    TraversalDirection,
    TraversalLimit,
)
from tarkka.domain.citations import WorkRelation, WorkRelationKind
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository


def _relation(
    subject: UUID,
    target: UUID,
    *,
    kind: WorkRelationKind = WorkRelationKind.CITES,
) -> WorkRelation:
    return WorkRelation(
        relation_id=uuid4(),
        subject_work_id=subject,
        object_work_id=target,
        kind=kind,
        basis=ObservationBasis.NATIVE,
        source_document_id=uuid4(),
    )


def _repository(tmp_path: Path, *relations: WorkRelation) -> JsonCitationRepository:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    for relation in relations:
        repository.save_relation(relation)
    return repository


def test_outbound_traversal_is_cycle_safe_and_depth_bounded(tmp_path: Path) -> None:
    root, second, third = uuid4(), uuid4(), uuid4()
    repository = _repository(
        tmp_path,
        _relation(root, second),
        _relation(second, third),
        _relation(third, root),
    )
    service = CitationTraversalService(repository)

    result = service.traverse(
        root,
        CitationTraversalPolicy(max_depth=1, max_works=10, max_relations=10),
    )

    assert result.work_ids == (root, second)
    assert len(result.relations) == 1
    assert result.max_depth_reached == 1
    assert result.stopped_by is TraversalLimit.DEPTH

    complete = service.traverse(
        root,
        CitationTraversalPolicy(max_depth=3, max_works=10, max_relations=10),
    )
    assert set(complete.work_ids) == {root, second, third}
    assert len(complete.relations) == 3
    assert complete.stopped_by is None


def test_inbound_traversal_walks_citing_works(tmp_path: Path) -> None:
    root, citer, citer_of_citer = uuid4(), uuid4(), uuid4()
    repository = _repository(
        tmp_path,
        _relation(citer, root),
        _relation(citer_of_citer, citer),
    )

    result = CitationTraversalService(repository).traverse(
        root,
        CitationTraversalPolicy(
            max_depth=2,
            direction=TraversalDirection.INBOUND,
        ),
    )

    assert result.work_ids == (root, citer, citer_of_citer)
    assert len(result.relations) == 2
    assert result.stopped_by is None


def test_both_direction_deduplicates_relations(tmp_path: Path) -> None:
    root, left, right = uuid4(), uuid4(), uuid4()
    inbound = _relation(left, root)
    outbound = _relation(root, right)
    repository = _repository(tmp_path, inbound, outbound)

    result = CitationTraversalService(repository).traverse(
        root,
        CitationTraversalPolicy(max_depth=1, direction=TraversalDirection.BOTH),
    )

    assert set(result.work_ids) == {root, left, right}
    assert {item.relation_id for item in result.relations} == {
        inbound.relation_id,
        outbound.relation_id,
    }


def test_work_limit_stops_before_exposing_unreturned_neighbor(tmp_path: Path) -> None:
    root, first, second = uuid4(), uuid4(), uuid4()
    repository = _repository(
        tmp_path,
        _relation(root, first),
        _relation(root, second),
    )

    result = CitationTraversalService(repository).traverse(
        root,
        CitationTraversalPolicy(max_depth=1, max_works=2, max_relations=10),
    )

    assert len(result.work_ids) == 2
    assert len(result.relations) == 1
    assert result.stopped_by is TraversalLimit.WORKS
    relation = result.relations[0]
    assert relation.subject_work_id in result.work_ids
    assert relation.object_work_id in result.work_ids


def test_relation_limit_is_hard(tmp_path: Path) -> None:
    root, first, second = uuid4(), uuid4(), uuid4()
    repository = _repository(
        tmp_path,
        _relation(root, first),
        _relation(root, second),
    )

    result = CitationTraversalService(repository).traverse(
        root,
        CitationTraversalPolicy(max_depth=2, max_works=10, max_relations=1),
    )

    assert len(result.relations) == 1
    assert len(result.work_ids) == 2
    assert result.stopped_by is TraversalLimit.RELATIONS


def test_relation_kind_filter_defaults_to_citations(tmp_path: Path) -> None:
    root, cited, dataset = uuid4(), uuid4(), uuid4()
    repository = _repository(
        tmp_path,
        _relation(root, cited),
        _relation(root, dataset, kind=WorkRelationKind.USES_DATASET),
    )
    service = CitationTraversalService(repository)

    citations_only = service.traverse(root)
    assert citations_only.work_ids == (root, cited)

    datasets_only = service.traverse(
        root,
        CitationTraversalPolicy(
            relation_kinds=frozenset({WorkRelationKind.USES_DATASET}),
        ),
    )
    assert datasets_only.work_ids == (root, dataset)


def test_zero_relation_budget_returns_only_root(tmp_path: Path) -> None:
    root, cited = uuid4(), uuid4()
    repository = _repository(tmp_path, _relation(root, cited))

    result = CitationTraversalService(repository).traverse(
        root,
        CitationTraversalPolicy(max_depth=1, max_relations=0),
    )

    assert result.work_ids == (root,)
    assert result.relations == ()
    assert result.stopped_by is TraversalLimit.RELATIONS


def test_policy_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="max_depth"):
        CitationTraversalPolicy(max_depth=-1)
    with pytest.raises(ValueError, match="max_works"):
        CitationTraversalPolicy(max_works=0)
    with pytest.raises(ValueError, match="max_relations"):
        CitationTraversalPolicy(max_relations=-1)
    with pytest.raises(ValueError, match="at least one relation kind"):
        CitationTraversalPolicy(relation_kinds=frozenset())
