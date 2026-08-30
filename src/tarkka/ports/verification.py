from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.citations import CitationContext, CitationMention
from tarkka.domain.extraction import EvidenceRecord, ExtractionRun, ResearchExtraction
from tarkka.domain.verification import EvidenceRelation


class ClaimEvidenceReader(Protocol):
    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None: ...

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None: ...


class ClaimLineageSourceReader(ClaimEvidenceReader, Protocol):
    """Read exact extraction objects plus their immutable run provenance."""

    def get_run(self, run_id: UUID) -> ExtractionRun | None: ...


class CitationContextLookup(Protocol):
    """Resolve one citation context scoped to its normalized Document."""

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None: ...


class CitationContextReader(CitationContextLookup, Protocol):
    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]: ...

    def list_mentions_for_ids(
        self, document_id: UUID, mention_ids: frozenset[UUID]
    ) -> tuple[CitationMention, ...]: ...

    def count_contexts_for_passages(
        self, document_id: UUID, passage_ids: frozenset[UUID]
    ) -> int: ...

    def list_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[CitationContext, ...]: ...

    def page_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[int, tuple[CitationContext, ...]]: ...


class EvidenceRelationReader(Protocol):
    """Bounded, internally consistent reads over immutable evidence assessments."""

    def page_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        """Return ``(total_count, page_slice)`` from one internally consistent read."""
        ...


class EvidenceRelationRepository(EvidenceRelationReader, Protocol):
    """Durable immutable assessment records with bounded claim reads."""

    def save_relation(self, relation: EvidenceRelation) -> None: ...

    def get_relation(self, relation_id: UUID) -> EvidenceRelation | None: ...

    def count_relations(self, claim_id: UUID) -> int: ...

    def list_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[EvidenceRelation, ...]: ...
