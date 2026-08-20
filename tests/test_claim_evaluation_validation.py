from __future__ import annotations

from uuid import uuid4

import pytest

from tarkka.domain.models import Document, Passage, Section
from tarkka.evaluation.claims import GoldClaim, GoldEvidenceSpan, evaluate_claims
from tarkka.infrastructure.extraction.rule_claims import RuleBasedClaimExtractor


def _document(text: str) -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
    )
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=0,
        title="Results",
        passages=(passage,),
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Evaluation fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
    )


def test_evaluation_rejects_gold_with_unknown_passage() -> None:
    document = _document("The study shows lower error.")
    batch = RuleBasedClaimExtractor().extract(document)
    gold = GoldClaim(
        evidence=(GoldEvidenceSpan(passage_id=uuid4(), char_start=0, char_end=5),)
    )

    with pytest.raises(ValueError, match="unknown passage"):
        evaluate_claims(batch, (gold,))


def test_evaluation_rejects_gold_span_beyond_passage_text() -> None:
    document = _document("The study shows lower error.")
    passage = document.sections[0].passages[0]
    batch = RuleBasedClaimExtractor().extract(document)
    gold = GoldClaim(
        evidence=(
            GoldEvidenceSpan(
                passage_id=passage.passage_id,
                char_start=0,
                char_end=len(passage.text) + 1,
            ),
        )
    )

    with pytest.raises(ValueError, match="exceeds"):
        evaluate_claims(batch, (gold,))


def test_evaluation_rejects_duplicate_gold_evidence_sets() -> None:
    document = _document("The study shows lower error.")
    passage = document.sections[0].passages[0]
    batch = RuleBasedClaimExtractor().extract(document)
    span = GoldEvidenceSpan(
        passage_id=passage.passage_id,
        char_start=0,
        char_end=len(passage.text),
    )

    with pytest.raises(ValueError, match="duplicate complete evidence sets"):
        evaluate_claims(
            batch,
            (
                GoldClaim(evidence=(span,)),
                GoldClaim(evidence=(span,)),
            ),
        )
