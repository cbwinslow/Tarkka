from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.citation_context import build_citation_contexts
from tarkka.application.citation_resolution import CitationResolutionService
from tarkka.application.citation_traversal import (
    CitationTraversalPolicy,
    CitationTraversalService,
    TraversalDirection,
)
from tarkka.application.citations import CitationIdentityResolver
from tarkka.domain.citations import (
    BibliographicReference,
    CitationMention,
    CitationResolution,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.models import Document, Passage, Section, Work
from tarkka.domain.source_observations import ObservationBasis
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.ports.citations import CitationRepository
from tarkka.ports.work_documents import WorkDocumentRepository
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
        text="alpha beta alpha",
        char_start=0,
        char_end=16,
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Citation fixture",
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


def _anchored_mention(
    document: Document,
    *,
    raw_text: str = "alpha",
    char_start: int | None = None,
    char_end: int | None = None,
) -> CitationMention:
    passage = document.sections[0].passages[0]
    return CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text=raw_text,
        section_id=passage.section_id,
        passage_id=passage.passage_id,
        char_start=char_start,
        char_end=char_end,
    )


def test_citation_context_rejects_cross_document_and_invalid_anchor_ranges() -> None:
    document = _document()
    passage = document.sections[0].passages[0]

    foreign = CitationMention(
        mention_id=uuid4(),
        document_id=uuid4(),
        raw_text="alpha",
    )
    with pytest.raises(ValueError, match="belong to context document"):
        build_citation_contexts(document, (foreign,))

    outside = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="alpha",
        passage_id=passage.passage_id,
        char_start=20,
        char_end=25,
    )
    with pytest.raises(ValueError, match="falls outside anchored passage"):
        build_citation_contexts(document, (outside,))

    mismatched = _anchored_mention(
        document,
        raw_text="alpha",
        char_start=1,
        char_end=6,
    )
    with pytest.raises(ValueError, match="does not match anchored passage text"):
        build_citation_contexts(document, (mismatched,))


@dataclass
class _Works:
    works: dict[UUID, Work] = field(default_factory=dict)
    identifiers: dict[tuple[str, str], Work] = field(default_factory=dict)
    lookup_calls: list[tuple[str, str]] = field(default_factory=list)

    def get_work(self, work_id: UUID) -> Work | None:
        return self.works.get(work_id)

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        self.lookup_calls.append((scheme, value))
        return self.identifiers.get((scheme, value))


@dataclass
class _Links:
    links: tuple[WorkDocumentLink, ...] = ()

    def list_document_work_links(self, document_id: UUID) -> tuple[WorkDocumentLink, ...]:
        return tuple(link for link in self.links if link.document_id == document_id)


@dataclass
class _CitationStore:
    references: tuple[BibliographicReference, ...] = ()
    resolutions: dict[UUID, CitationResolution] = field(default_factory=dict)

    def get_resolution(self, reference_id: UUID) -> CitationResolution | None:
        return self.resolutions.get(reference_id)

    def save_resolution(self, resolution: CitationResolution) -> None:
        self.resolutions[resolution.reference_id] = resolution

    def list_references(
        self,
        document_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[BibliographicReference, ...]:
        selected = tuple(
            reference
            for reference in self.references
            if reference.document_id == document_id
        )[offset:]
        return selected if limit is None else selected[:limit]

    def count_references(self, document_id: UUID) -> int:
        return sum(
            reference.document_id == document_id for reference in self.references
        )

    def get_or_create_relation(self, relation: WorkRelation) -> WorkRelation:
        return relation


def test_exact_identity_resolver_normalizes_each_identifier_scheme_independently() -> None:
    work = Work(work_id=uuid4(), title="Matched work")
    works = _Works(
        identifiers={
            ("custom", "canonical-id"): work,
            ("doi", "10.1000/abc"): work,
            ("arxiv", "2401.00001"): work,
        }
    )
    resolver = CitationIdentityResolver(cast(WorkRepository, works))
    cases = (
        ({"custom": "canonical-id"}, ("custom", "canonical-id")),
        ({"doi": "10.1000/ABC"}, ("doi", "10.1000/abc")),
        ({"arxiv": "2401.00001"}, ("arxiv", "2401.00001")),
    )

    for identifiers, expected_lookup in cases:
        works.lookup_calls.clear()
        reference = BibliographicReference(
            reference_id=uuid4(),
            document_id=uuid4(),
            ordinal=0,
            raw_text="Reference",
            identifiers=identifiers,
        )

        resolution = resolver.resolve(reference)

        assert resolution.work_id == work.work_id
        assert works.lookup_calls == [expected_lookup]


def test_resolution_service_validates_pagination_and_allows_explicit_work_without_links() -> None:
    work = Work(work_id=uuid4(), title="Citing work")
    works = _Works(works={work.work_id: work})
    links = _Links()
    citations = _CitationStore()
    service = CitationResolutionService(
        cast(CitationRepository, citations),
        cast(WorkRepository, works),
        cast(WorkDocumentRepository, links),
    )
    document_id = uuid4()

    with pytest.raises(ValueError, match="offset and limit must be non-negative"):
        service.resolve_document(document_id, offset=-1)
    with pytest.raises(ValueError, match="offset and limit must be non-negative"):
        service.resolve_document(document_id, limit=-1)

    result = service.resolve_document(document_id, citing_work_id=work.work_id)
    assert result.citing_work_id == work.work_id
    assert result.total_references == 0


def _relation(subject: UUID, object_: UUID) -> WorkRelation:
    return WorkRelation(
        relation_id=uuid4(),
        subject_work_id=subject,
        object_work_id=object_,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=uuid4(),
    )


@dataclass
class _TraversalRepository:
    outbound: dict[UUID, tuple[WorkRelation, ...]] = field(default_factory=dict)
    inbound: dict[UUID, tuple[WorkRelation, ...]] = field(default_factory=dict)

    @staticmethod
    def _select(
        relations: tuple[WorkRelation, ...],
        *,
        kinds: frozenset[WorkRelationKind] | None,
        exclude_ids: frozenset[UUID],
        limit: int | None,
    ) -> tuple[WorkRelation, ...]:
        selected = tuple(
            relation
            for relation in relations
            if relation.relation_id not in exclude_ids
            and (kinds is None or relation.kind in kinds)
        )
        return selected if limit is None else selected[:limit]

    def list_relations_from(
        self,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None = None,
        exclude_ids: frozenset[UUID] = frozenset(),
        limit: int | None = None,
    ) -> tuple[WorkRelation, ...]:
        return self._select(
            self.outbound.get(work_id, ()),
            kinds=kinds,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    def list_relations_to(
        self,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None = None,
        exclude_ids: frozenset[UUID] = frozenset(),
        limit: int | None = None,
    ) -> tuple[WorkRelation, ...]:
        return self._select(
            self.inbound.get(work_id, ()),
            kinds=kinds,
            exclude_ids=exclude_ids,
            limit=limit,
        )


def test_traversal_policy_rejects_negative_relation_budget_and_empty_kinds() -> None:
    with pytest.raises(ValueError, match="max_relations must be non-negative"):
        CitationTraversalPolicy(max_relations=-1)
    with pytest.raises(ValueError, match="at least one relation kind"):
        CitationTraversalPolicy(relation_kinds=frozenset())


def test_traversal_ignores_foreign_relation_from_repository() -> None:
    root = uuid4()
    foreign = _relation(uuid4(), uuid4())
    repository = _TraversalRepository(outbound={root: (foreign,)})
    service = CitationTraversalService(cast(CitationRepository, repository))

    result = service.traverse(root, CitationTraversalPolicy(max_depth=1))

    assert result.work_ids == (root,)
    assert result.relations == ()


def test_traversal_exhausts_exact_relation_budget_without_false_stop() -> None:
    root = uuid4()
    neighbor = uuid4()
    relation = _relation(root, neighbor)
    repository = _TraversalRepository(outbound={root: (relation,)})
    service = CitationTraversalService(cast(CitationRepository, repository))

    result = service.traverse(
        root,
        CitationTraversalPolicy(max_depth=2, max_relations=1),
    )

    assert result.work_ids == (root, neighbor)
    assert result.relations == (relation,)
    assert result.stopped_by is None


def test_traversal_inbound_relation_uses_subject_as_neighbor() -> None:
    root = uuid4()
    neighbor = uuid4()
    relation = _relation(neighbor, root)
    repository = _TraversalRepository(inbound={root: (relation,)})
    service = CitationTraversalService(cast(CitationRepository, repository))

    result = service.traverse(
        root,
        CitationTraversalPolicy(max_depth=1, direction=TraversalDirection.INBOUND),
    )

    assert result.work_ids == (root, neighbor)
    assert result.relations == (relation,)
