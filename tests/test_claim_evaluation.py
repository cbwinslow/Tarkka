from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from tarkka.domain.extraction import AttributionKind
from tarkka.domain.models import Document, Passage, Section
from tarkka.evaluation.claims import GoldClaim, GoldEvidenceSpan, evaluate_claims
from tarkka.infrastructure.extraction.model_claims import ModelClaimExtractor
from tarkka.infrastructure.extraction.rule_claims import RuleBasedClaimExtractor
from tarkka.ports.model_claims import EvidenceSelector, ModelClaimCandidate, ModelClaimRequest


@dataclass
class _FixtureModel:
    candidates: tuple[ModelClaimCandidate, ...]
    provider: str = "fixture"
    model_name: str = "fixture-model"
    model_version: str | None = "1"

    def extract_claims(self, request: ModelClaimRequest) -> tuple[ModelClaimCandidate, ...]:
        """Return the predefined claim candidates for the model request.
        
        Args:
            request: Model claim extraction request.
        
        Returns:
            The configured model claim candidates.
        """
        return self.candidates


def _document(text: str) -> Document:
    """
    Create a single-section document fixture containing the provided passage text.
    
    Args:
        text: The text to place in the document's only passage.
    
    Returns:
        A document with generated identifiers and character offsets spanning the passage.
    """
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
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Evaluation fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=0,
                title="Results",
                passages=(passage,),
            ),
        ),
    )


def _gold(document: Document, text: str) -> GoldClaim:
    """
    Create a gold claim whose evidence span covers the first occurrence of the given text.
    
    Args:
        document: The document containing the passage to search.
        text: The text whose first occurrence defines the evidence span.
    
    Returns:
        A gold claim containing the matching evidence span.
    
    Raises:
        ValueError: If the text does not occur in the first passage.
    """
    passage = document.sections[0].passages[0]
    start = passage.text.index(text)
    return GoldClaim(
        evidence=(
            GoldEvidenceSpan(
                passage_id=passage.passage_id,
                char_start=start,
                char_end=start + len(text),
            ),
        )
    )


def test_rule_extractor_reports_precision_and_recall_from_exact_evidence() -> None:
    expected = "The study shows lower error."
    extra = "The model predicts higher accuracy."
    document = _document(f"Background. {expected} {extra}")

    report = evaluate_claims(
        RuleBasedClaimExtractor().extract(document),
        (_gold(document, expected),),
    )

    assert report.true_positives == 1
    assert report.false_positives == 1
    assert report.false_negatives == 0
    assert report.precision == 0.5
    assert report.recall == 1.0
    assert report.f1 == 2 / 3
    assert report.attribution_accuracy == 1.0


def test_model_paraphrase_matches_gold_by_exact_supporting_span() -> None:
    evidence_text = "Held-out log loss improved by 8%."
    document = _document(f"Background. {evidence_text}")
    passage = document.sections[0].passages[0]
    start = passage.text.index(evidence_text)
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="The model improved held-out performance.",
                evidence=(
                    EvidenceSelector(
                        passage_id=passage.passage_id,
                        char_start=start,
                        char_end=start + len(evidence_text),
                    ),
                ),
                confidence=0.9,
            ),
        )
    )

    report = evaluate_claims(
        ModelClaimExtractor(model).extract(document),
        (_gold(document, evidence_text),),
    )

    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0


def test_duplicate_model_candidates_with_identical_evidence_match_one_to_one() -> None:
    evidence_text = "The model improved performance by 12%."
    document = _document(evidence_text)
    passage = document.sections[0].passages[0]
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="Performance improved by 12%.",
                evidence=(
                    EvidenceSelector(
                        passage_id=passage.passage_id,
                        char_start=0,
                        char_end=len(evidence_text),
                    ),
                ),
                confidence=0.9,
            ),
            ModelClaimCandidate(
                text="The model showed a 12% improvement.",
                evidence=(
                    EvidenceSelector(
                        passage_id=passage.passage_id,
                        char_start=0,
                        char_end=len(evidence_text),
                    ),
                ),
                confidence=0.85,
            ),
        )
    )

    report = evaluate_claims(
        ModelClaimExtractor(model).extract(document),
        (_gold(document, evidence_text),),
    )

    assert report.true_positives == 1
    assert report.false_positives == 1
    assert report.false_negatives == 0


def test_attribution_accuracy_is_measured_separately_from_detection() -> None:
    evidence_text = "The analysis identified a measurable association."
    document = _document(evidence_text)
    passage = document.sections[0].passages[0]
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="An association was identified.",
                evidence=(EvidenceSelector(passage.passage_id, 0, len(evidence_text)),),
                confidence=0.7,
                attribution=AttributionKind.EXTRACTOR_INFERRED,
            ),
        )
    )

    report = evaluate_claims(
        ModelClaimExtractor(model).extract(document),
        (_gold(document, evidence_text),),
    )

    assert report.true_positives == 1
    assert report.attribution_accuracy == 0.0


def test_empty_gold_treats_all_predictions_as_false_positives() -> None:
    document = _document("The study shows lower error.")

    report = evaluate_claims(RuleBasedClaimExtractor().extract(document), ())

    assert report.true_positives == 0
    assert report.false_positives == 1
    assert report.false_negatives == 0
    assert report.precision == 0.0
    assert report.recall == 0.0
    assert report.f1 == 0.0
    assert report.attribution_accuracy is None
