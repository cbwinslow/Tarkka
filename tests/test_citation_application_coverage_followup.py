from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

from tarkka.application.citation_context import build_citation_contexts
from tarkka.application.citation_traversal import (
    CitationTraversalPolicy,
    CitationTraversalService,
    TraversalDirection,
)
from tarkka.application.citations import CitationIdentityResolver
from tarkka.domain.citations import (
    BibliographicReference,
    CitationMention,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.models import Document, Passage, Section, Work
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.ports.works import WorkRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _document() -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="alpha beta",
        char_start=0,
        char_end=10,
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Citation follow-up fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=0,
                title="Body",
                passages=(passage,),
            ),
        ),
    )


def test_anchored_citation_without_explicit_bounds_uses_full_passage_context() -> None:
    document = _document()
    passage = document.sections[0].passages[0]
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="alpha",
        passage_id=passage.passage_id,
    )

    contexts = build_citation_contexts(document, (mention,))

    assert len(contexts) == 1
    assert contexts[0].passage_id == passage.passage_id


class _NoWorks:
    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        del scheme, value
        return None


def test_identity_resolver_skips_identifier_that_cannot_be_normalized() -> None:
    resolver = CitationIdentityResolver(cast(WorkRepository, _NoWorks()))
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Invalid DOI reference",
        identifiers={"doi": "not-a-doi"},
    )

    assert resolver.resolve(reference).work_id is None


def test_traversal_policy_rejects_invalid_direction_and_relation_kind() -> None:
    # These casts intentionally model malformed values arriving from an untyped
    # configuration/deserialization boundary so the runtime guards are exercised.
    with pytest.raises(ValueError, match="direction must be a TraversalDirection"):
        CitationTraversalPolicy(direction=cast(TraversalDirection, "outbound"))
    with pytest.raises(ValueError, match="relation kinds must be WorkRelationKind"):
        CitationTraversalPolicy(
            relation_kinds=cast(frozenset[WorkRelationKind], frozenset({"cites"}))
        )


def test_traversal_exact_relation_cap_with_no_new_frontier_finishes_cleanly(
    tmp_path,
) -> None:
    root = uuid4()
    relation = WorkRelation(
        relation_id=uuid4(),
        subject_work_id=root,
        object_work_id=root,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=uuid4(),
    )
    repository = JsonCitationRepository(tmp_path / "citations.json")
    repository.save_relation(relation)
    service = CitationTraversalService(repository)

    result = service.traverse(
        root,
        CitationTraversalPolicy(max_depth=2, max_relations=1),
    )

    assert result.work_ids == (root,)
    assert result.relations == (relation,)
    assert result.stopped_by is None
