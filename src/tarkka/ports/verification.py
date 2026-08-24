from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import EvidenceRecord, ResearchExtraction
from tarkka.domain.verification import EvidenceRelation


class ClaimEvidenceReader(Protocol):
    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None: ...

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None: ...


class CitationContextReader(Protocol):
    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]: ...


class EvidenceRelationRepository(Protocol):
    """Durable immutable assessment records with bounded claim reads."""

    def save_relation(self, relation: EvidenceRelation) -> None: ...

    def get_relation(self, relation_id: UUID) -> EvidenceRelation | None: ...

    def count_relations(self, claim_id: UUID) -> int: ...

    def list_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[EvidenceRelation, ...]: ...
