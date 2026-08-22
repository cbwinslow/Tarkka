from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.citations import (
    BibliographicReference,
    CitationContext,
    CitationMention,
    CitationResolution,
    WorkRelation,
)


class CitationRepository(Protocol):
    """Persistence boundary for bibliography, citation, and Work-relation state.

    Implementations must serialize writes that target the same stable identity. In
    particular, one reference has one resolution key: concurrent ``save_resolution``
    calls must not allow incompatible resolutions to overwrite each other silently.
    File-backed adapters may use an exclusive lock; SQL adapters should enforce the
    invariant with a unique constraint plus transactional/upsert semantics.
    """

    def save_reference(self, reference: BibliographicReference) -> None: ...

    def save_mention(self, mention: CitationMention) -> None: ...

    def save_context(self, context: CitationContext) -> None: ...

    def save_resolution(self, resolution: CitationResolution) -> None:
        """Persist one auditable resolution without losing a conflicting concurrent write."""
        ...

    def save_relation(self, relation: WorkRelation) -> None: ...

    def list_references(self, document_id: UUID) -> tuple[BibliographicReference, ...]: ...

    def list_mentions(self, document_id: UUID) -> tuple[CitationMention, ...]: ...

    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]: ...

    def get_resolution(self, reference_id: UUID) -> CitationResolution | None: ...

    def get_relation(self, relation_id: UUID) -> WorkRelation | None: ...

    def list_relations_from(self, work_id: UUID) -> tuple[WorkRelation, ...]: ...

    def list_relations_to(self, work_id: UUID) -> tuple[WorkRelation, ...]: ...
