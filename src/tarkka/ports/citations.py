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

    Implementations must serialize writes to a reference's resolution key. They must also
    implement ``get_or_create_relation`` atomically so concurrent attempts to persist the same
    deterministic relation return one stored relation rather than surfacing a duplicate race.
    """

    def save_reference(self, reference: BibliographicReference) -> None: ...

    def save_mention(self, mention: CitationMention) -> None: ...

    def save_context(self, context: CitationContext) -> None: ...

    def save_resolution(self, resolution: CitationResolution) -> None: ...

    def save_relation(self, relation: WorkRelation) -> None: ...

    def get_or_create_relation(self, relation: WorkRelation) -> WorkRelation: ...

    def list_references(self, document_id: UUID) -> tuple[BibliographicReference, ...]: ...

    def list_mentions(self, document_id: UUID) -> tuple[CitationMention, ...]: ...

    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]: ...

    def get_resolution(self, reference_id: UUID) -> CitationResolution | None: ...

    def get_relation(self, relation_id: UUID) -> WorkRelation | None: ...

    def list_relations_from(self, work_id: UUID) -> tuple[WorkRelation, ...]: ...

    def list_relations_to(self, work_id: UUID) -> tuple[WorkRelation, ...]: ...
