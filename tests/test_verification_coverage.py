from __future__ import annotations

from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.verification import (
    CitationContextNotFoundError,
    CitationRepositoryNotAvailableError,
    ClaimNotFoundError,
    EvidenceNotFoundError,
    EvidenceVerificationRequest,
    EvidenceVerificationService,
)
from tarkka.domain.citations import CitationContext, CitationMention
from tarkka.domain.extraction import (
    Claim,
    Evidence,
    EvidenceRecord,
    FigureEvidence,
    ResearchExtraction,
)
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.evaluation.verification import GoldEvidenceRelation
from tarkka.ports.verification import (
    CitationContextReader,
    ClaimEvidenceReader,
    EvidenceRelationRepository,
)
from tests.test_json_extraction_repository_contract import _batch

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _Reader:
    def __init__(
        self,
        extractions: tuple[ResearchExtraction, ...],
        evidence: tuple[EvidenceRecord, ...],
    ) -> None:
        self._extractions = {item.extraction_id: item for item in extractions}
        self._evidence = {item.evidence_id: item for item in evidence}

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        return self._extractions.get(extraction_id)

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        return self._evidence.get(evidence_id)


class _Relations:
    def __init__(self) -> None:
        self._values: dict[UUID, EvidenceRelation] = {}

    def save_relation(self, relation: EvidenceRelation) -> None:
        self._values[relation.relation_id] = relation

    def get_relation(self, relation_id: UUID) -> EvidenceRelation | None:
        return self._values.get(relation_id)

    def count_relations(self, claim_id: UUID) -> int:
        return sum(value.claim_id == claim_id for value in self._values.values())

    def list_relations(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[EvidenceRelation, ...]:
        values = tuple(value for value in self._values.values() if value.claim_id == claim_id)
        return values[offset : offset + limit]


class _Citations:
    def __init__(self, contexts: tuple[CitationContext, ...] = ()) -> None:
        self._contexts = {item.context_id: item for item in contexts}

    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]:
        return tuple(item for item in self._contexts.values() if item.document_id == document_id)

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        context = self._contexts.get(context_id)
        return context if context is not None and context.document_id == document_id else None

    def list_mentions_for_ids(
        self,
        document_id: UUID,
        mention_ids: frozenset[UUID],
    ) -> tuple[CitationMention, ...]:
        del document_id, mention_ids
        return ()

    def count_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
    ) -> int:
        return len(self.list_contexts_for_passages(document_id, passage_ids))

    def list_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[CitationContext, ...]:
        values = tuple(
            context
            for context in self._contexts.values()
            if context.document_id == document_id and context.passage_id in passage_ids
        )
        if limit is None:
            return values[offset:]
        return values[offset : offset + limit]

    def page_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[int, tuple[CitationContext, ...]]:
        values = self.list_contexts_for_passages(document_id, passage_ids)
        page = values[offset:] if limit is None else values[offset : offset + limit]
        return len(values), page


def _service(
    reader: _Reader,
    *,
    citations: _Citations | None = None,
) -> EvidenceVerificationService:
    return EvidenceVerificationService(
        source=cast(ClaimEvidenceReader, reader),
        relations=cast(EvidenceRelationRepository, _Relations()),
        citations=cast(CitationContextReader, citations) if citations is not None else None,
    )


def _claim_and_evidence() -> tuple[Claim, Evidence]:
    batch = _batch()
    claim = next(item for item in batch.extractions if isinstance(item, Claim))
    evidence = batch.evidence[0]
    assert isinstance(evidence, Evidence)
    return claim, evidence


@pytest.mark.parametrize(("offset", "limit"), [(-1, 1), (0, -1)])
def test_citation_candidates_reject_negative_bounds(offset: int, limit: int) -> None:
    claim, evidence = _claim_and_evidence()
    service = _service(_Reader((claim,), (evidence,)))

    with pytest.raises(ValueError, match="offset and limit must be non-negative"):
        service.citation_candidates(claim.extraction_id, offset=offset, limit=limit)


def test_citation_candidates_fail_closed_when_claim_evidence_is_missing() -> None:
    claim, _ = _claim_and_evidence()
    service = _service(_Reader((claim,), ()))

    with pytest.raises(EvidenceNotFoundError, match="evidence not found"):
        service.citation_candidates(claim.extraction_id)


def test_citation_candidates_keep_passage_evidence_when_figure_evidence_is_mixed_in() -> None:
    claim, passage_evidence = _claim_and_evidence()
    figure = FigureEvidence(
        evidence_id=uuid4(),
        document_id=claim.document_id,
        figure_id=uuid4(),
        provenance=claim.provenance,
    )
    claim = replace(
        claim,
        evidence_ids=(passage_evidence.evidence_id, figure.evidence_id),
    )
    context = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=claim.document_id,
        text=passage_evidence.text,
        char_start=0,
        char_end=len(passage_evidence.text),
        section_id=passage_evidence.section_id,
        passage_id=passage_evidence.passage_id,
    )
    service = _service(
        _Reader((claim,), (passage_evidence, figure)),
        citations=_Citations((context,)),
    )

    page = service.citation_candidates(claim.extraction_id)

    assert page.document_id == claim.document_id
    assert page.total == 1
    assert len(page.candidates) == 1
    assert page.candidates[0].citation_context == context
    assert page.candidates[0].evidence_ids == (passage_evidence.evidence_id,)


def test_citation_context_rejects_missing_repository_and_context() -> None:
    claim, evidence = _claim_and_evidence()
    service = _service(_Reader((claim,), (evidence,)))
    context_id = uuid4()

    with pytest.raises(CitationRepositoryNotAvailableError, match="repository is not available"):
        service.citation_context(claim.document_id, context_id)

    service = _service(_Reader((claim,), (evidence,)), citations=_Citations())
    with pytest.raises(CitationContextNotFoundError, match="citation context not found"):
        service.citation_context(claim.document_id, context_id)


def test_record_fails_closed_for_missing_claim_or_exact_evidence() -> None:
    claim, evidence = _claim_and_evidence()
    reader = _Reader((claim,), (evidence,))
    service = _service(reader)

    with pytest.raises(ClaimNotFoundError, match="claim not found"):
        service.record(
            EvidenceVerificationRequest(
                claim_id=uuid4(),
                evidence_id=evidence.evidence_id,
                kind=EvidenceRelationKind.SUPPORTS,
                verifier_name="fixture",
                verifier_version="1",
                confidence=0.8,
            )
        )

    with pytest.raises(ValueError, match="must identify exact evidence"):
        service.record(
            EvidenceVerificationRequest(
                claim_id=claim.extraction_id,
                kind=EvidenceRelationKind.SUPPORTS,
                verifier_name="fixture",
                verifier_version="1",
                confidence=0.8,
            )
        )

    missing_evidence_id = uuid4()
    with pytest.raises(EvidenceNotFoundError, match="evidence not found"):
        service.record(
            EvidenceVerificationRequest(
                claim_id=claim.extraction_id,
                evidence_id=missing_evidence_id,
                kind=EvidenceRelationKind.SUPPORTS,
                verifier_name="fixture",
                verifier_version="1",
                confidence=0.8,
            )
        )


def test_record_with_context_fails_closed_without_citation_repository() -> None:
    claim, evidence = _claim_and_evidence()
    service = _service(_Reader((claim,), (evidence,)))

    with pytest.raises(CitationContextNotFoundError, match="citation context not found"):
        service.record(
            EvidenceVerificationRequest(
                claim_id=claim.extraction_id,
                evidence_id=evidence.evidence_id,
                citation_context_id=uuid4(),
                kind=EvidenceRelationKind.SUPPORTS,
                verifier_name="fixture",
                verifier_version="1",
                confidence=0.8,
            )
        )


def test_gold_evidence_relation_rejects_invalid_kind_and_missing_exact_evidence() -> None:
    claim_id = uuid4()

    with pytest.raises(ValueError, match="kind must be an EvidenceRelationKind"):
        GoldEvidenceRelation(
            claim_id,
            cast(EvidenceRelationKind, "supports"),
            uuid4(),
        )

    with pytest.raises(ValueError, match="must identify exact evidence"):
        GoldEvidenceRelation(claim_id, EvidenceRelationKind.SUPPORTS)
