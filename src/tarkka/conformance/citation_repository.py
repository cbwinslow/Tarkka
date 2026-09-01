from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from tarkka.conformance._assertions import _expect_exception
from tarkka.domain.citations import (
    BibliographicReference,
    CitationContext,
    CitationMention,
    CitationResolution,
    WorkRelation,
)
from tarkka.ports.citations import CitationRepository


class CitationRepositoryContract:
    """Reusable persistence assertions for citation graph repositories."""

    @staticmethod
    def assert_missing_reads_are_empty(
        repository: CitationRepository,
        missing_reference_id: UUID,
        missing_relation_id: UUID,
    ) -> None:
        assert repository.get_resolution(missing_reference_id) is None
        assert repository.get_relation(missing_relation_id) is None

    @staticmethod
    def assert_graph_round_trip(
        repository: CitationRepository,
        reference: BibliographicReference,
        mention: CitationMention,
        context: CitationContext,
        resolution: CitationResolution,
        relation: WorkRelation,
    ) -> None:
        repository.save_reference(reference)
        repository.save_mention(mention)
        repository.save_context(context)
        repository.save_resolution(resolution)
        repository.save_relation(relation)

        assert repository.list_references(reference.document_id) == (reference,)
        assert repository.list_mentions(reference.document_id) == (mention,)
        assert repository.list_contexts(reference.document_id) == (context,)
        assert repository.get_context(reference.document_id, context.context_id) == context
        assert repository.get_resolution(reference.reference_id) == resolution
        assert repository.get_relation(relation.relation_id) == relation
        assert repository.list_relations_from(relation.subject_work_id) == (relation,)
        assert repository.list_relations_to(relation.object_work_id) == (relation,)

    @staticmethod
    def assert_reference_save_is_idempotent(
        repository: CitationRepository,
        reference: BibliographicReference,
    ) -> None:
        repository.save_reference(reference)
        repository.save_reference(reference)
        assert repository.list_references(reference.document_id) == (reference,)

    @staticmethod
    def assert_reference_conflict_fails_closed(
        repository: CitationRepository,
        original: BibliographicReference,
        conflicting: BibliographicReference,
        conflict_error: type[Exception],
    ) -> None:
        assert original.reference_id == conflicting.reference_id
        assert original != conflicting

        repository.save_reference(original)
        _expect_exception(
            conflict_error,
            lambda: repository.save_reference(conflicting),
        )
        assert repository.list_references(original.document_id) == (original,)

    @staticmethod
    def assert_resolution_can_evolve(
        repository: CitationRepository,
        first: CitationResolution,
        ambiguous: CitationResolution,
        evolved: CitationResolution,
        conflicting_identity: CitationResolution,
        conflict_error: type[Exception],
    ) -> None:
        assert (
            first.reference_id
            == ambiguous.reference_id
            == evolved.reference_id
            == conflicting_identity.reference_id
        )
        assert first.resolution_id == ambiguous.resolution_id == evolved.resolution_id
        assert conflicting_identity.resolution_id != first.resolution_id
        assert ambiguous.candidate_work_ids

        repository.save_resolution(first)
        repository.save_resolution(ambiguous)
        assert repository.get_resolution(first.reference_id) == ambiguous
        repository.save_resolution(evolved)
        assert repository.get_resolution(first.reference_id) == evolved

        _expect_exception(
            conflict_error,
            lambda: repository.save_resolution(conflicting_identity),
        )
        assert repository.get_resolution(first.reference_id) == evolved

    @staticmethod
    def assert_relation_get_or_create_is_idempotent(
        repository: CitationRepository,
        first: WorkRelation,
        logically_same_later: WorkRelation,
    ) -> None:
        assert first.relation_id == logically_same_later.relation_id

        assert repository.get_or_create_relation(first) == first
        assert repository.get_or_create_relation(logically_same_later) == first
        assert repository.get_relation(first.relation_id) == first
        assert repository.list_relations_from(first.subject_work_id) == (first,)
        assert repository.list_relations_to(first.object_work_id) == (first,)

    @staticmethod
    def assert_relation_get_or_create_is_atomic(
        repository: CitationRepository,
        relation: WorkRelation,
    ) -> None:
        workers = 8
        barrier = Barrier(workers)

        def persist(_: int) -> WorkRelation:
            barrier.wait(timeout=10)
            return repository.get_or_create_relation(relation)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = tuple(executor.map(persist, range(workers)))

        assert results == (relation,) * workers
        assert repository.get_relation(relation.relation_id) == relation
        assert repository.list_relations_from(relation.subject_work_id) == (relation,)
        assert repository.list_relations_to(relation.object_work_id) == (relation,)

    @staticmethod
    def assert_relation_conflict_fails_closed(
        repository: CitationRepository,
        original: WorkRelation,
        conflicting: WorkRelation,
        conflict_error: type[Exception],
    ) -> None:
        assert original.relation_id == conflicting.relation_id
        assert original != conflicting

        repository.get_or_create_relation(original)
        _expect_exception(
            conflict_error,
            lambda: repository.get_or_create_relation(conflicting),
        )
        assert repository.get_relation(original.relation_id) == original

    @staticmethod
    def assert_relation_query_bounds(
        repository: CitationRepository,
        relation: WorkRelation,
        outbound_peer: WorkRelation,
        inbound_peer: WorkRelation,
    ) -> None:
        assert relation.subject_work_id == outbound_peer.subject_work_id
        assert relation.object_work_id == inbound_peer.object_work_id
        repository.save_relation(relation)
        repository.save_relation(outbound_peer)
        repository.save_relation(inbound_peer)

        outbound = repository.list_relations_from(relation.subject_work_id)
        assert relation in outbound
        assert outbound_peer in outbound
        assert repository.list_relations_from(relation.subject_work_id, limit=0) == ()
        assert len(repository.list_relations_from(relation.subject_work_id, limit=1)) == 1
        assert repository.list_relations_from(
            relation.subject_work_id,
            kinds=frozenset({outbound_peer.kind}),
            exclude_ids=frozenset({relation.relation_id}),
            limit=1,
        ) == (outbound_peer,)

        inbound = repository.list_relations_to(relation.object_work_id)
        assert relation in inbound
        assert inbound_peer in inbound
        assert repository.list_relations_to(relation.object_work_id, limit=0) == ()
        assert len(repository.list_relations_to(relation.object_work_id, limit=1)) == 1
        assert repository.list_relations_to(
            relation.object_work_id,
            kinds=frozenset({inbound_peer.kind}),
            exclude_ids=frozenset({relation.relation_id}),
            limit=1,
        ) == (inbound_peer,)
