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
from tarkka.infrastructure.extraction.model_batching import (
    ModelBatchingPolicy,
    build_model_requests,
    validate_candidate_batch_scope,
)
from tarkka.ports.model_claims import ModelClaimCandidate, StructuredClaimModel

_TARKKA_MODEL_CLAIM_NAMESPACE = UUID("bb6f9fbd-b8d0-577f-b165-c954466634d4")
_CandidateSignature = tuple[str, str, str, tuple[tuple[str, int, int], ...]]


class NoModelClaimsFoundError(ValueError):
    """Raised when a model returns no structured claim candidates."""


class ModelClaimExtractor:
    """Convert bounded structured model responses into evidence-backed claims."""

    name = "model-claims"
    version = "1.2.0"

    def __init__(
        self,
        model: StructuredClaimModel,
        *,
        batching: ModelBatchingPolicy | None = None,
    ) -> None:
        if not model.provider.strip() or not model.model_name.strip():
            raise ValueError("model provider/name must not be blank")
        if model.model_version is not None and not model.model_version.strip():
            raise ValueError("model version must not be blank when provided")
        self.model = model
        self.batching = batching or ModelBatchingPolicy()

    def extract(self, document: Document) -> ExtractionBatch:
        passages = tuple(passage for section in document.sections for passage in section.passages)
        requests = build_model_requests(document, passages, self.batching)
        all_passage_ids = {passage.passage_id for passage in passages}
        candidates: list[ModelClaimCandidate] = []
        candidate_index: dict[_CandidateSignature, int] = {}

        for request in requests:
            allowed_passage_ids = {passage.passage_id for passage in request.passages}
            for candidate in self.model.extract_claims(request):
                validate_candidate_batch_scope(
                    candidate,
                    allowed_passage_ids,
                    all_passage_ids,
                )
                signature = _candidate_signature(candidate)
                existing_index = candidate_index.get(signature)
                if existing_index is None:
                    candidate_index[signature] = len(candidates)
                    candidates.append(candidate)
                elif candidate.confidence > candidates[existing_index].confidence:
                    candidates[existing_index] = candidate

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

        for current_candidate_index, candidate in enumerate(candidates):
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
                    f"evidence:{run_id}:{current_candidate_index}:{selector_index}:"
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
                f"claim:{run_id}:{current_candidate_index}:{candidate.text}",
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


def _candidate_signature(candidate: ModelClaimCandidate) -> _CandidateSignature:
    evidence = tuple(
        sorted(
            (
                str(selector.passage_id),
                selector.char_start,
                selector.char_end,
            )
            for selector in candidate.evidence
        )
    )
    normalized_text = " ".join(candidate.text.split()).casefold()
    return (
        normalized_text,
        candidate.claim_type.casefold(),
        candidate.attribution.value,
        evidence,
    )


def _resolve_passage(passages: dict[UUID, Passage], passage_id: UUID) -> Passage:
    return passages[passage_id]
