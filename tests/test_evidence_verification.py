from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.verification import (
    CitationContextNotFoundError,
    EvidenceVerificationRequest,
    EvidenceVerificationService,
)
from tarkka.domain.citations import CitationContext, CitationMention
from tarkka.domain.extraction import Claim, Evidence, ExtractionBatch
from tarkka.domain.verification import EvidenceRelationKind
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tests.test_json_extraction_repository_contract import _batch


@dataclass(frozen=True)
class _Fixture:
    batch: ExtractionBatch
    claim: Claim
    evidence: Evidence
    relations: JsonVerificationRepository
    citations: JsonCitationRepository
    service: EvidenceVerificationService


def _service(tmp_path: Path) -> _Fixture:
    batch = _batch()
    source = JsonExtractionRepository(tmp_path / "extractions.json")
    source.save_batch(batch)
    relations = JsonVerificationRepository(tmp_path / "verifications.json")
    citations = JsonCitationRepository(tmp_path / "citations.json")
    claim = next(item for item in batch.extractions if isinstance(item, Claim))
    evidence = next(item for item in batch.evidence if isinstance(item, Evidence))
    return _Fixture(
        batch=batch,
        claim=claim,
        evidence=evidence,
        relations=relations,
        citations=citations,
        service=EvidenceVerificationService(
            source=source,
            relations=relations,
            citations=citations,
        ),
    )


def test_verification_records_exact_evidence_with_citation_context(tmp_path: Path) -> None:
    fixture = _service(tmp_path)
    context = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=fixture.batch.document_id,
        text="The source cites [1].",
        char_start=0,
        char_end=len("The source cites [1]."),
    )
    fixture.citations.save_context(context)
    request = EvidenceVerificationRequest(
        claim_id=fixture.claim.extraction_id,
        evidence_id=fixture.evidence.evidence_id,
        citation_context_id=context.context_id,
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.9,
        reasoning_summary="Exact result span supports the stated claim.",
    )

    first = fixture.service.record(request)
    second = fixture.service.record(request)

    assert first == second
    assert first.evidence_id == fixture.evidence.evidence_id
    assert first.citation_context_id == context.context_id
    assert fixture.relations.count_relations(fixture.claim.extraction_id) == 1


def test_no_evidence_is_explicit_and_context_must_belong_to_claim_document(
    tmp_path: Path,
) -> None:
    fixture = _service(tmp_path)
    relation = fixture.service.record(
        EvidenceVerificationRequest(
            claim_id=fixture.claim.extraction_id,
            kind=EvidenceRelationKind.NO_EVIDENCE,
            verifier_name="human-review",
            verifier_version="1",
            confidence=0.7,
        )
    )
    assert relation.evidence_id is None

    with pytest.raises(ValueError, match="must not identify evidence"):
        fixture.service.record(
            EvidenceVerificationRequest(
                claim_id=fixture.claim.extraction_id,
                evidence_id=fixture.evidence.evidence_id,
                kind=EvidenceRelationKind.NO_EVIDENCE,
                verifier_name="human-review",
                verifier_version="1",
                confidence=0.7,
            )
        )
    with pytest.raises(CitationContextNotFoundError, match="citation context not found"):
        fixture.service.record(
            EvidenceVerificationRequest(
                claim_id=fixture.claim.extraction_id,
                evidence_id=fixture.evidence.evidence_id,
                citation_context_id=uuid4(),
                kind=EvidenceRelationKind.UNCERTAIN,
                verifier_name="human-review",
                verifier_version="1",
                confidence=0.2,
            )
        )
    assert fixture.batch.document_id == fixture.claim.document_id


def test_citation_candidates_are_bounded_to_exact_claim_evidence_passages(tmp_path: Path) -> None:
    fixture = _service(tmp_path)
    anchored = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=fixture.batch.document_id,
        text=fixture.evidence.text,
        char_start=0,
        char_end=len(fixture.evidence.text),
        section_id=fixture.evidence.section_id,
        passage_id=fixture.evidence.passage_id,
    )
    unanchored = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=fixture.batch.document_id,
        text="[2]",
        char_start=0,
        char_end=3,
    )
    fixture.citations.save_context(anchored)
    fixture.citations.save_context(unanchored)
    reference_id = uuid4()
    fixture.citations.save_mention(
        CitationMention(
            mention_id=anchored.mention_id,
            document_id=fixture.batch.document_id,
            raw_text="[1]",
            reference_id=reference_id,
            passage_id=fixture.evidence.passage_id,
        )
    )

    page = fixture.service.citation_candidates(fixture.claim.extraction_id, limit=1)

    assert page.total == 1
    assert len(page.candidates) == 1
    assert page.candidates[0].citation_context == anchored
    assert page.candidates[0].evidence_ids == (fixture.evidence.evidence_id,)
    assert page.candidates[0].reference_id == reference_id


def test_citation_candidates_return_claim_document_for_empty_candidate_sets(tmp_path: Path) -> None:
    fixture = _service(tmp_path)
    service = EvidenceVerificationService(
        source=JsonExtractionRepository(tmp_path / "extractions.json"),
        relations=fixture.relations,
    )

    page = service.citation_candidates(fixture.claim.extraction_id)

    assert page.document_id == fixture.batch.document_id
    assert page.total == 0
    assert page.candidates == ()
