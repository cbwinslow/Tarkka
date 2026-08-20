from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from uuid import uuid4

import pytest

import tarkka.evaluation as evaluation_package
from tarkka.domain.extraction import (
    AttributionKind,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    Hypothesis,
)
from tarkka.domain.models import Document, Passage, Section
from tarkka.evaluation.claims import (
    ClaimEvaluationReport,
    GoldClaim,
    GoldEvidenceSpan,
    evaluate_claims,
)
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


def _selector(document: Document, text: str) -> EvidenceSelector:
    """Build a model evidence selector covering the first occurrence of `text`."""
    passage = document.sections[0].passages[0]
    start = passage.text.index(text)
    return EvidenceSelector(
        passage_id=passage.passage_id,
        char_start=start,
        char_end=start + len(text),
    )


def _gold_span(document: Document, text: str) -> GoldEvidenceSpan:
    """Build the gold evidence span covering the first occurrence of `text`."""
    return _gold(document, text).evidence[0]


class TestGoldEvidenceSpan:
    def test_rejects_negative_char_start(self) -> None:
        with pytest.raises(ValueError, match="invalid gold evidence character range"):
            GoldEvidenceSpan(passage_id=uuid4(), char_start=-1, char_end=5)

    def test_rejects_empty_range(self) -> None:
        with pytest.raises(ValueError, match="invalid gold evidence character range"):
            GoldEvidenceSpan(passage_id=uuid4(), char_start=5, char_end=5)

    def test_rejects_inverted_range(self) -> None:
        with pytest.raises(ValueError, match="invalid gold evidence character range"):
            GoldEvidenceSpan(passage_id=uuid4(), char_start=5, char_end=3)

    def test_equal_spans_are_equal_and_hash_equal(self) -> None:
        passage_id = uuid4()
        first = GoldEvidenceSpan(passage_id=passage_id, char_start=0, char_end=5)
        second = GoldEvidenceSpan(passage_id=passage_id, char_start=0, char_end=5)

        assert first == second
        assert hash(first) == hash(second)
        assert len({first, second}) == 1

    def test_spans_are_orderable_by_field_order(self) -> None:
        passage_id = uuid4()
        earlier = GoldEvidenceSpan(passage_id=passage_id, char_start=0, char_end=5)
        later = GoldEvidenceSpan(passage_id=passage_id, char_start=10, char_end=15)

        assert earlier < later
        assert sorted([later, earlier]) == [earlier, later]

    def test_is_immutable(self) -> None:
        span = GoldEvidenceSpan(passage_id=uuid4(), char_start=0, char_end=5)

        with pytest.raises(FrozenInstanceError):
            span.char_start = 1  # type: ignore[misc]


class TestGoldClaim:
    def test_requires_at_least_one_evidence_span(self) -> None:
        with pytest.raises(ValueError, match="gold claim must contain evidence"):
            GoldClaim(evidence=())

    def test_rejects_duplicate_evidence_spans(self) -> None:
        span = GoldEvidenceSpan(passage_id=uuid4(), char_start=0, char_end=5)

        with pytest.raises(ValueError, match="gold claim evidence spans must be unique"):
            GoldClaim(evidence=(span, span))

    def test_defaults_attribution_to_author_stated(self) -> None:
        span = GoldEvidenceSpan(passage_id=uuid4(), char_start=0, char_end=5)

        claim = GoldClaim(evidence=(span,))

        assert claim.attribution is AttributionKind.AUTHOR_STATED

    def test_accepts_explicit_attribution(self) -> None:
        span = GoldEvidenceSpan(passage_id=uuid4(), char_start=0, char_end=5)

        claim = GoldClaim(evidence=(span,), attribution=AttributionKind.SYNTHESIS)

        assert claim.attribution is AttributionKind.SYNTHESIS


class TestClaimEvaluationReport:
    def test_is_immutable(self) -> None:
        report = evaluate_claims(
            RuleBasedClaimExtractor().extract(_document("The study shows lower error.")),
            (),
        )

        assert isinstance(report, ClaimEvaluationReport)
        with pytest.raises(FrozenInstanceError):
            report.true_positives = 99  # type: ignore[misc]


def test_multi_span_claim_matches_only_the_full_gold_evidence_set() -> None:
    evidence_a = "The study shows lower error."
    evidence_b = "The model predicts higher accuracy."
    document = _document(f"Background. {evidence_a} {evidence_b}")
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="The study shows lower error and the model predicts higher accuracy.",
                evidence=(_selector(document, evidence_a), _selector(document, evidence_b)),
                confidence=0.85,
            ),
        )
    )
    gold = GoldClaim(evidence=(_gold_span(document, evidence_a), _gold_span(document, evidence_b)))

    report = evaluate_claims(ModelClaimExtractor(model).extract(document), (gold,))

    assert report.true_positives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 0
    assert report.precision == 1.0
    assert report.recall == 1.0


def test_multi_span_claim_does_not_partially_match_a_gold_subset() -> None:
    evidence_a = "The study shows lower error."
    evidence_b = "The model predicts higher accuracy."
    document = _document(f"Background. {evidence_a} {evidence_b}")
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="The study shows lower error and the model predicts higher accuracy.",
                evidence=(_selector(document, evidence_a), _selector(document, evidence_b)),
                confidence=0.85,
            ),
        )
    )
    # Gold only requires the first span, not the full two-span evidence set.
    partial_gold = _gold(document, evidence_a)

    report = evaluate_claims(ModelClaimExtractor(model).extract(document), (partial_gold,))

    assert report.true_positives == 0
    assert report.false_positives == 1
    assert report.false_negatives == 1


def test_evidence_span_order_does_not_affect_matching() -> None:
    evidence_a = "The study shows lower error."
    evidence_b = "The model predicts higher accuracy."
    document = _document(f"Background. {evidence_a} {evidence_b}")
    # Selectors are supplied in the reverse order relative to the gold evidence tuple.
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="Combined claim.",
                evidence=(_selector(document, evidence_b), _selector(document, evidence_a)),
                confidence=0.85,
            ),
        )
    )
    gold = GoldClaim(evidence=(_gold_span(document, evidence_a), _gold_span(document, evidence_b)))

    report = evaluate_claims(ModelClaimExtractor(model).extract(document), (gold,))

    assert report.true_positives == 1
    assert report.false_positives == 0


def test_duplicate_predictions_with_identical_evidence_count_as_false_positives() -> None:
    evidence_text = "The analysis identified a measurable association."
    document = _document(f"Background. {evidence_text}")
    selector = _selector(document, evidence_text)
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="An association was identified.",
                evidence=(selector,),
                confidence=0.7,
            ),
            ModelClaimCandidate(
                text="A measurable association was found.",
                evidence=(selector,),
                confidence=0.6,
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
    assert report.precision == 0.5
    assert report.recall == 1.0


def test_attribution_accuracy_averages_across_multiple_matched_claims() -> None:
    evidence_a = "The study shows lower error."
    evidence_b = "The model predicts higher accuracy."
    document = _document(f"Background. {evidence_a} {evidence_b}")
    model = _FixtureModel(
        candidates=(
            ModelClaimCandidate(
                text="Error was reduced.",
                evidence=(_selector(document, evidence_a),),
                confidence=0.9,
                # Matches the gold default attribution (AUTHOR_STATED).
            ),
            ModelClaimCandidate(
                text="Accuracy was improved.",
                evidence=(_selector(document, evidence_b),),
                confidence=0.9,
                attribution=AttributionKind.EXTRACTOR_INFERRED,
            ),
        )
    )

    report = evaluate_claims(
        ModelClaimExtractor(model).extract(document),
        (_gold(document, evidence_a), _gold(document, evidence_b)),
    )

    assert report.true_positives == 2
    assert report.attribution_accuracy == 0.5


def test_non_claim_extractions_are_excluded_from_predictions() -> None:
    document = _document("A hypothesis about the mechanism is proposed.")
    passage = document.sections[0].passages[0]
    run_id = uuid4()
    run = ExtractionRun(
        run_id=run_id,
        document_id=document.document_id,
        extractor_name="fixture-non-claim",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=run_id, confidence=1.0)
    evidence_id = uuid4()
    evidence = Evidence.from_passage(
        evidence_id=evidence_id,
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    hypothesis = Hypothesis(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(evidence_id,),
        provenance=provenance,
        text="A hypothesis about the mechanism is proposed.",
    )
    batch = ExtractionBatch(
        document=document,
        run=run,
        evidence=(evidence,),
        extractions=(hypothesis,),
    )
    gold = GoldClaim(
        evidence=(GoldEvidenceSpan(passage_id=passage.passage_id, char_start=0, char_end=5),)
    )

    report = evaluate_claims(batch, (gold,))

    assert report.true_positives == 0
    assert report.false_positives == 0
    assert report.false_negatives == 1
    assert report.precision == 0.0
    assert report.recall == 0.0
    assert report.f1 == 0.0
    assert report.attribution_accuracy is None


def test_evaluation_package_reexports_public_api() -> None:
    from tarkka.evaluation import claims as claims_module

    assert evaluation_package.evaluate_claims is claims_module.evaluate_claims
    assert evaluation_package.GoldClaim is claims_module.GoldClaim
    assert evaluation_package.GoldEvidenceSpan is claims_module.GoldEvidenceSpan
    assert evaluation_package.ClaimEvaluationReport is claims_module.ClaimEvaluationReport
    assert set(evaluation_package.__all__) == {
        "ClaimEvaluationReport",
        "GoldClaim",
        "GoldEvidenceSpan",
        "evaluate_claims",
    }
