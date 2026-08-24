"""Validation and persistence of evidence-verification assessments."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.extraction import Claim, EvidenceRecord, HumanReviewState
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.ports.verification import (
    CitationContextReader,
    ClaimEvidenceReader,
    EvidenceRelationRepository,
)


class ClaimNotFoundError(LookupError):
    pass


class EvidenceNotFoundError(LookupError):
    pass


class CitationContextNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceVerificationRequest:
    claim_id: UUID
    kind: EvidenceRelationKind
    verifier_name: str
    verifier_version: str
    confidence: float
    evidence_id: UUID | None = None
    citation_context_id: UUID | None = None
    human_review_state: HumanReviewState = HumanReviewState.UNREVIEWED
    reasoning_summary: str | None = None


class EvidenceVerificationService:
    """Fail closed on unknown claim/evidence/context lineage before persisting an assessment."""

    def __init__(
        self,
        *,
        source: ClaimEvidenceReader,
        relations: EvidenceRelationRepository,
        citations: CitationContextReader | None = None,
    ) -> None:
        self._source = source
        self._relations = relations
        self._citations = citations

    def record(self, request: EvidenceVerificationRequest) -> EvidenceRelation:
        claim = self._claim(request.claim_id)
        evidence = self._evidence(request)
        self._validate_context(claim, request.citation_context_id)
        relation = EvidenceRelation(
            relation_id=_relation_id(request),
            claim_id=claim.extraction_id,
            kind=request.kind,
            verifier_name=request.verifier_name,
            verifier_version=request.verifier_version,
            confidence=request.confidence,
            human_review_state=request.human_review_state,
            evidence_id=evidence.evidence_id if evidence is not None else None,
            citation_context_id=request.citation_context_id,
            reasoning_summary=request.reasoning_summary,
        )
        self._relations.save_relation(relation)
        return self._relations.get_relation(relation.relation_id) or relation

    def _claim(self, claim_id: UUID) -> Claim:
        value = self._source.get_extraction(claim_id)
        if not isinstance(value, Claim):
            raise ClaimNotFoundError(f"claim not found: {claim_id}")
        return value

    def _evidence(self, request: EvidenceVerificationRequest) -> EvidenceRecord | None:
        if request.kind is EvidenceRelationKind.NO_EVIDENCE:
            if request.evidence_id is not None:
                raise ValueError("no_evidence verification must not identify evidence")
            return None
        if request.evidence_id is None:
            raise ValueError("verification must identify exact evidence")
        evidence = self._source.get_evidence(request.evidence_id)
        if evidence is None:
            raise EvidenceNotFoundError(f"evidence not found: {request.evidence_id}")
        return evidence

    def _validate_context(self, claim: Claim, context_id: UUID | None) -> None:
        if context_id is None:
            return
        if self._citations is None:
            raise CitationContextNotFoundError(f"citation context not found: {context_id}")
        if not any(
            context.context_id == context_id
            for context in self._citations.list_contexts(claim.document_id)
        ):
            raise CitationContextNotFoundError(f"citation context not found: {context_id}")


def _relation_id(request: EvidenceVerificationRequest) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "tarkka:evidence-relation",
                str(request.claim_id),
                request.kind.value,
                str(request.evidence_id) if request.evidence_id is not None else "none",
                (
                    str(request.citation_context_id)
                    if request.citation_context_id is not None
                    else "none"
                ),
                request.verifier_name,
                request.verifier_version,
            )
        ),
    )
