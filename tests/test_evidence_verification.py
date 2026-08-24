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
from tarkka.domain.citations import CitationContext
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
