from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.citations import (
    BibliographicReference,
    CitationContext,
    CitationMention,
    CitationResolution,
    WorkRelation,
    WorkRelationKind,
)


class CitationRepository(Protocol):
    """Persistence boundary for bibliography, citation, and Work-relation state.

    Implementations must serialize writes to a reference's resolution key. They must also
    implement ``get_or_create_relation`` atomically so concurrent attempts to persist the same
    deterministic relation return one stored relation rather than surfacing a duplicate race.

    Relation-list queries accept filtering, exclusions, and a hard result limit so application
    traversal budgets can reach the storage boundary. SQL adapters should translate these into
    WHERE/ORDER BY/LIMIT rather than materializing an unbounded adjacency list first.
    """

    def save_reference(self, reference: BibliographicReference) -> None: ...

    def save_mention(self, mention: CitationMention) -> None: ...

    def save_context(self, context: CitationContext) -> None: ...

    def save_resolution(self, resolution: CitationResolution) -> None: ...

    def save_relation(self, relation: WorkRelation) -> None: ...

    def get_or_create_relation(self, relation: WorkRelation) -> WorkRelation: ...

    def count_references(self, document_id: UUID) -> int: ...

    def list_references(
        self,
        document_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[BibliographicReference, ...]: ...

    def list_mentions(self, document_id: UUID) -> tuple[CitationMention, ...]: ...

    def list_mentions_for_reference(
        self, document_id: UUID, reference_id: UUID
    ) -> tuple[CitationMention, ...]: ...

    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]: ...

    def list_contexts_for_mentions(
        self, document_id: UUID, mention_ids: frozenset[UUID]
    ) -> tuple[CitationContext, ...]: ...

    def get_resolution(self, reference_id: UUID) -> CitationResolution | None: ...

    def get_relation(self, relation_id: UUID) -> WorkRelation | None: ...

    def list_relations_from(
        self,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None = None,
        exclude_ids: frozenset[UUID] = frozenset(),
        limit: int | None = None,
    ) -> tuple[WorkRelation, ...]: ...

    def list_relations_to(
        self,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None = None,
        exclude_ids: frozenset[UUID] = frozenset(),
        limit: int | None = None,
    ) -> tuple[WorkRelation, ...]: ...
