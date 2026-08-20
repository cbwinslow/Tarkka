from __future__ import annotations

from uuid import UUID, uuid4, uuid5

from tarkka.domain.extraction import (
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    ModelProvenance,
)
from tarkka.domain.models import Document, Passage
from tarkka.ports.model_claims import ModelClaimRequest, ModelPassage, StructuredClaimModel

_TARKKA_MODEL_CLAIM_NAMESPACE = UUID("bb6f9fbd-b8d0-577f-b165-c954466634d4")


class NoModelClaimsFoundError(ValueError):
    """Raised when a model returns no structured claim candidates."""


class ModelClaimExtractor:
    """Convert structured model candidates into evidence-backed Tarkka claims."""

    name = "model-claims"
    version = "1.0.0"

    def __init__(self, model: StructuredClaimModel) -> None:
        if not model.provider.strip() or not model.model_name.strip():
            raise ValueError("model provider/name must not be blank")
        if model.model_version is not None and not model.model_version.strip():
            raise ValueError("model version must not be blank when provided")
        self.model = model

    def extract(self, document: Document) -> ExtractionBatch:
        passages = tuple(
            passage
            for section in document.sections
            for passage in section.passages
        )
        request = ModelClaimRequest(
            document_id=document.document_id,
            title=document.title,
            passages=tuple(
                ModelPassage(
                    passage_id=passage.passage_id,
                    section_id=passage.section_id,
                    ordinal=passage.ordinal,
                    text=passage.text,
                )
                for passage in passages
            ),
        )
        candidates = self.model.extract_claims(request)
        if not candidates:
            raise NoModelClaimsFoundError("model returned no structured claim candidates")

        run_id = uuid4()
        run = ExtractionRun(
            run_id=run_id,
            document_id=document.document_id,
            extractor_name=self.name,
            extractor_version=self.version,
            model=ModelProvenance(
                provider=self.model.provider,
                name=self.model.model_name,
                version=self.model.model_version,
            ),
        )
        passage_index = {passage.passage_id: passage for passage in passages}
        evidence: list[Evidence] = []
        claims: list[Claim] = []

        for candidate_index, candidate in enumerate(candidates):
            provenance = ExtractionProvenance(
                run_id=run_id,
                confidence=candidate.confidence,
                reasoning_summary=candidate.reasoning_summary,
            )
            evidence_ids: list[UUID] = []
            for selector_index, selector in enumerate(candidate.evidence):
                passage = _resolve_passage(passage_index, selector.passage_id)
                evidence_id = uuid5(
                    _TARKKA_MODEL_CLAIM_NAMESPACE,
                    f"evidence:{run_id}:{candidate_index}:{selector_index}:"
                    f"{selector.passage_id}:{selector.char_start}:{selector.char_end}",
                )
                evidence.append(
                    Evidence.from_passage(
                        evidence_id=evidence_id,
                        passage=passage,
                        passage_char_start=selector.char_start,
                        passage_char_end=selector.char_end,
                        provenance=provenance,
                    )
                )
                evidence_ids.append(evidence_id)

            claim_id = uuid5(
                _TARKKA_MODEL_CLAIM_NAMESPACE,
                f"claim:{run_id}:{candidate_index}:{candidate.text}",
            )
            claims.append(
                Claim(
                    extraction_id=claim_id,
                    document_id=document.document_id,
                    evidence_ids=tuple(evidence_ids),
                    provenance=provenance,
                    attribution=candidate.attribution,
                    text=candidate.text,
                    claim_type=candidate.claim_type,
                )
            )

        return ExtractionBatch(
            document=document,
            run=run,
            evidence=tuple(evidence),
            extractions=tuple(claims),
        )


def _resolve_passage(passages: dict[UUID, Passage], passage_id: UUID) -> Passage:
    try:
        return passages[passage_id]
    except KeyError as exc:
        raise ValueError(f"model evidence references unknown passage: {passage_id}") from exc
