from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from tarkka.domain.extraction import ExtractionBatch, ExtractionProvenance
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.extraction import model_research
from tarkka.infrastructure.extraction.model_batching import (
    ModelBatchingPolicy,
    build_model_requests,
)
from tarkka.infrastructure.extraction.model_claims import ModelClaimExtractor
from tarkka.infrastructure.extraction.model_research import ModelResearchExtractor
from tarkka.infrastructure.extraction.rule_claims import _claim_spans
from tarkka.ports.extraction import StructuredExtractor, validate_extractor_output
from tarkka.ports.model_claims import (
    EvidenceSelector,
    ModelClaimCandidate,
    ModelClaimRequest,
    ModelPassage,
)
from tarkka.ports.model_research import (
    ModelMethodCandidate,
    ModelResearchCandidate,
    ModelResearchRequest,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@dataclass
class _ClaimModel:
    provider: str = "fixture"
    model_name: str = "claim-model"
    model_version: str | None = "1"
    candidates: tuple[ModelClaimCandidate, ...] = ()

    def extract_claims(self, request: ModelClaimRequest) -> tuple[ModelClaimCandidate, ...]:
        del request
        return self.candidates


@dataclass
class _ResearchModel:
    provider: str = "fixture"
    model_name: str = "research-model"
    model_version: str | None = "1"
    candidates: tuple[ModelResearchCandidate, ...] = ()

    def extract_research(
        self, request: ModelResearchRequest
    ) -> tuple[ModelResearchCandidate, ...]:
        del request
        return self.candidates


class _Extractor:
    name = "fixture"
    version = "1"

    def extract(self, document: Document) -> ExtractionBatch:
        del document
        raise NotImplementedError


def _document() -> Document:
    document_id = uuid4()
    section_id = uuid4()
    text = "The fitted model improved outcomes."
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
        title="Model extraction coverage fixture",
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


def _selector(document: Document) -> EvidenceSelector:
    passage = document.sections[0].passages[0]
    return EvidenceSelector(passage.passage_id, 0, len(passage.text))


def test_build_model_requests_accepts_empty_passage_sequence() -> None:
    assert build_model_requests(_document(), (), ModelBatchingPolicy()) == ()


def test_model_claim_extractor_rejects_blank_version() -> None:
    with pytest.raises(ValueError, match="model version must not be blank"):
        ModelClaimExtractor(_ClaimModel(model_version=" "))


def test_model_claim_equal_confidence_duplicate_retains_first_candidate() -> None:
    document = _document()
    evidence = (_selector(document),)
    first = ModelClaimCandidate(
        text="Model improved outcomes",
        evidence=evidence,
        confidence=0.8,
        reasoning_summary="first",
    )
    duplicate = ModelClaimCandidate(
        text="  model   improved outcomes  ",
        evidence=evidence,
        confidence=0.8,
        reasoning_summary="second",
    )

    batch = ModelClaimExtractor(_ClaimModel(candidates=(first, duplicate))).extract(document)

    assert len(batch.extractions) == 1
    assert batch.extractions[0].provenance.reasoning_summary == "first"


def test_model_research_extractor_rejects_blank_identity_fields() -> None:
    with pytest.raises(ValueError, match="provider/name must not be blank"):
        ModelResearchExtractor(_ResearchModel(provider=" "))
    with pytest.raises(ValueError, match="model version must not be blank"):
        ModelResearchExtractor(_ResearchModel(model_version=" "))


def test_model_research_equal_confidence_duplicate_retains_first_candidate() -> None:
    document = _document()
    evidence = (_selector(document),)
    first = ModelMethodCandidate(
        name="Gradient Boosted Trees",
        evidence=evidence,
        confidence=0.8,
        reasoning_summary="first",
    )
    duplicate = ModelMethodCandidate(
        name="  gradient   boosted trees ",
        evidence=evidence,
        confidence=0.8,
        reasoning_summary="second",
    )

    batch = ModelResearchExtractor(
        _ResearchModel(candidates=(first, duplicate))
    ).extract(document)

    assert len(batch.extractions) == 1
    assert batch.extractions[0].provenance.reasoning_summary == "first"


def test_model_research_helpers_fail_closed_on_unsupported_candidate() -> None:
    unsupported = cast(ModelResearchCandidate, object())

    with pytest.raises(TypeError, match="unsupported research candidate"):
        model_research._candidate_kind(unsupported)
    with pytest.raises(TypeError, match="unsupported research candidate"):
        model_research._candidate_primary(unsupported)
    with pytest.raises(TypeError, match="unsupported research candidate"):
        model_research._candidate_details(unsupported)
    with pytest.raises(TypeError, match="unsupported research candidate"):
        model_research._to_domain_record(
            unsupported,
            extraction_id=uuid4(),
            document_id=uuid4(),
            evidence_ids=(),
            provenance=ExtractionProvenance(run_id=uuid4(), confidence=1.0),
        )


def test_model_claim_port_invariants_fail_closed() -> None:
    passage_id = uuid4()
    section_id = uuid4()
    valid_passage = ModelPassage(
        passage_id=passage_id,
        section_id=section_id,
        ordinal=0,
        text="x",
    )
    duplicate_passage = ModelPassage(
        passage_id=passage_id,
        section_id=section_id,
        ordinal=1,
        text="y",
    )
    selector = EvidenceSelector(passage_id, 0, 1)

    with pytest.raises(ValueError, match="ordinal must be non-negative"):
        ModelPassage(
            passage_id=uuid4(),
            section_id=section_id,
            ordinal=-1,
            text="x",
        )
    with pytest.raises(ValueError, match="text must not be empty"):
        ModelPassage(
            passage_id=uuid4(),
            section_id=section_id,
            ordinal=0,
            text="",
        )
    with pytest.raises(ValueError, match="must contain passages"):
        ModelClaimRequest(document_id=uuid4(), title="fixture", passages=())
    with pytest.raises(ValueError, match="passage IDs must be unique"):
        ModelClaimRequest(
            document_id=uuid4(),
            title="fixture",
            passages=(valid_passage, duplicate_passage),
        )
    with pytest.raises(ValueError, match="invalid model evidence character range"):
        EvidenceSelector(passage_id, -1, 1)
    with pytest.raises(ValueError, match="text/type must not be blank"):
        ModelClaimCandidate(text=" ", evidence=(selector,), confidence=0.5)
    with pytest.raises(ValueError, match="text/type must not be blank"):
        ModelClaimCandidate(
            text="claim",
            claim_type=" ",
            evidence=(selector,),
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="must cite evidence"):
        ModelClaimCandidate(text="claim", evidence=(), confidence=0.5)
    with pytest.raises(ValueError, match="selectors must be unique"):
        ModelClaimCandidate(
            text="claim",
            evidence=(selector, selector),
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        ModelClaimCandidate(text="claim", evidence=(selector,), confidence=1.1)
    with pytest.raises(ValueError, match="reasoning summary must not be blank"):
        ModelClaimCandidate(
            text="claim",
            evidence=(selector,),
            confidence=0.5,
            reasoning_summary=" ",
        )


def test_model_research_port_invariants_fail_closed() -> None:
    selector = EvidenceSelector(uuid4(), 0, 1)

    with pytest.raises(ValueError, match="primary text must not be blank"):
        ModelMethodCandidate(name=" ", evidence=(selector,), confidence=0.5)
    with pytest.raises(ValueError, match="candidate must cite evidence"):
        ModelMethodCandidate(name="method", evidence=(), confidence=0.5)
    with pytest.raises(ValueError, match="selectors must be unique"):
        ModelMethodCandidate(
            name="method",
            evidence=(selector, selector),
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        ModelMethodCandidate(name="method", evidence=(selector,), confidence=-0.1)
    with pytest.raises(ValueError, match="reasoning summary must not be blank"):
        ModelMethodCandidate(
            name="method",
            evidence=(selector,),
            confidence=0.5,
            reasoning_summary=" ",
        )
    with pytest.raises(ValueError, match="description must not be blank"):
        ModelMethodCandidate(
            name="method",
            evidence=(selector,),
            confidence=0.5,
            description=" ",
        )


def test_validate_extractor_output_rejects_name_and_version_mismatch() -> None:
    document = _document()
    extractor: StructuredExtractor = _Extractor()

    wrong_name = cast(
        ExtractionBatch,
        SimpleNamespace(
            document_id=document.document_id,
            run=SimpleNamespace(extractor_name="other", extractor_version="1"),
        ),
    )
    with pytest.raises(ValueError, match="extractor name does not match"):
        validate_extractor_output(extractor, document, wrong_name)

    wrong_version = cast(
        ExtractionBatch,
        SimpleNamespace(
            document_id=document.document_id,
            run=SimpleNamespace(extractor_name="fixture", extractor_version="2"),
        ),
    )
    with pytest.raises(ValueError, match="extractor version does not match"):
        validate_extractor_output(extractor, document, wrong_version)


def test_rule_claims_ignore_whitespace_only_sentence() -> None:
    assert _claim_spans("   ") == ()
