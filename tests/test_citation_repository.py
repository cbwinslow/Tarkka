from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.citations import (
    BibliographicReference,
    CitationContext,
    CitationMention,
    CitationResolution,
    CitationResolutionStatus,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.json_citation_repository import (
    CitationConflictError,
    JsonCitationRepository,
)


def test_json_citation_repository_round_trips_full_citation_graph(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=2,
        raw_text="Example reference",
        identifiers={"doi": "10.1000/example"},
        source_observation_id=uuid4(),
    )
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[2]",
        reference_id=reference.reference_id,
        char_start=10,
        char_end=13,
    )
    context = CitationContext(
        context_id=uuid4(),
        mention_id=mention.mention_id,
        document_id=document_id,
        text="See [2]",
        char_start=6,
        char_end=13,
    )
    cited_work_id = uuid4()
    resolution = CitationResolution(
        resolution_id=uuid4(),
        reference_id=reference.reference_id,
        status=CitationResolutionStatus.RESOLVED,
        work_id=cited_work_id,
        resolver="exact_identifier",
        source_observation_id=reference.source_observation_id,
    )
    citing_work_id = uuid4()
    relation = WorkRelation(
        relation_id=uuid4(),
        subject_work_id=citing_work_id,
        object_work_id=cited_work_id,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=document_id,
        source_reference_id=reference.reference_id,
    )

    repository.save_reference(reference)
    repository.save_mention(mention)
    repository.save_context(context)
    repository.save_resolution(resolution)
    repository.save_relation(relation)

    reopened = JsonCitationRepository(tmp_path / "citations.json")
    assert reopened.list_references(document_id) == (reference,)
    assert reopened.list_mentions(document_id) == (mention,)
    assert reopened.list_contexts(document_id) == (context,)
    assert reopened.get_resolution(reference.reference_id) == resolution
    assert reopened.list_relations_from(citing_work_id) == (relation,)
    assert reopened.list_relations_to(cited_work_id) == (relation,)


def test_json_citation_repository_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Example reference",
    )

    repository.save_reference(reference)
    repository.save_reference(reference)

    assert repository.list_references(reference.document_id) == (reference,)


def test_json_citation_repository_rejects_conflicting_stable_ids(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Example reference",
    )
    repository.save_reference(reference)

    with pytest.raises(CitationConflictError, match="conflicting reference"):
        repository.save_reference(replace(reference, raw_text="Different reference"))


def test_resolution_state_can_evolve_for_same_stable_resolution(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference_id = uuid4()
    resolution_id = uuid4()
    first = CitationResolution(
        resolution_id=resolution_id,
        reference_id=reference_id,
        status=CitationResolutionStatus.UNRESOLVED,
        resolver="exact_identifier",
    )
    repository.save_resolution(first)

    resolved = CitationResolution(
        resolution_id=resolution_id,
        reference_id=reference_id,
        status=CitationResolutionStatus.RESOLVED,
        work_id=uuid4(),
        resolver="exact_identifier",
    )
    repository.save_resolution(resolved)

    assert repository.get_resolution(reference_id) == resolved


def test_resolution_rejects_different_identity_for_same_reference(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference_id = uuid4()
    repository.save_resolution(
        CitationResolution(
            resolution_id=uuid4(),
            reference_id=reference_id,
            status=CitationResolutionStatus.UNRESOLVED,
        )
    )

    with pytest.raises(CitationConflictError, match="conflicting resolution identity"):
        repository.save_resolution(
            CitationResolution(
                resolution_id=uuid4(),
                reference_id=reference_id,
                status=CitationResolutionStatus.RESOLVED,
                work_id=uuid4(),
            )
        )


def test_repository_rejects_directory_catalog_path(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "citations"
    catalog_dir.mkdir()

    with pytest.raises(ValueError, match="is a directory"):
        JsonCitationRepository(catalog_dir)


def test_repository_rejects_catalog_with_missing_bucket(tmp_path: Path) -> None:
    path = tmp_path / "citations.json"
    path.write_text(json.dumps({"schema_version": 1, "references": {}}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid citation catalog bucket"):
        JsonCitationRepository(path).list_references(uuid4())


def test_repository_orders_references_and_mentions_deterministically(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    later_reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=5,
        raw_text="Later",
    )
    earlier_reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=1,
        raw_text="Earlier",
    )
    later_mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[5]",
        char_start=20,
        char_end=23,
    )
    earlier_mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[1]",
        char_start=2,
        char_end=5,
    )

    repository.save_reference(later_reference)
    repository.save_reference(earlier_reference)
    repository.save_mention(later_mention)
    repository.save_mention(earlier_mention)

    assert repository.list_references(document_id) == (earlier_reference, later_reference)
    assert repository.list_mentions(document_id) == (earlier_mention, later_mention)


def test_repository_pages_references_without_materializing_domain_records(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    references = tuple(
        BibliographicReference(
            reference_id=uuid4(),
            document_id=document_id,
            ordinal=ordinal,
            raw_text=f"Reference {ordinal}",
        )
        for ordinal in (4, 1, 3, 2)
    )
    for reference in references:
        repository.save_reference(reference)

    assert repository.count_references(document_id) == 4
    assert [
        item.ordinal
        for item in repository.list_references(document_id, offset=1, limit=2)
    ] == [2, 3]
    assert repository.list_references(document_id, offset=0, limit=0) == ()


def test_repository_pages_contexts_for_exact_passages(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    passage_id = uuid4()
    matching = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=document_id,
        text="[1]",
        char_start=0,
        char_end=3,
        passage_id=passage_id,
    )
    other = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=document_id,
        text="[2]",
        char_start=4,
        char_end=7,
        passage_id=uuid4(),
    )
    repository.save_context(matching)
    repository.save_context(other)

    assert repository.count_contexts_for_passages(document_id, frozenset()) == 0
    assert repository.count_contexts_for_passages(document_id, frozenset({passage_id})) == 1
    assert repository.list_contexts_for_passages(document_id, frozenset()) == ()
    assert repository.list_contexts_for_passages(
        document_id, frozenset({passage_id}), limit=0
    ) == ()
    assert repository.list_contexts_for_passages(
        document_id, frozenset({passage_id}), limit=None
    ) == (matching,)


def test_open_existing_does_not_initialize_missing_catalog(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "citations.json"

    assert JsonCitationRepository.open_existing(path) is None
    assert not path.parent.exists()
