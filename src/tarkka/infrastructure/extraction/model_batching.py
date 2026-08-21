from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from tarkka.domain.models import Document, Passage
from tarkka.ports.model_claims import EvidenceSelector, ModelClaimRequest, ModelPassage


class EvidenceGroundedCandidate(Protocol):
    evidence: tuple[EvidenceSelector, ...]


@dataclass(frozen=True, slots=True)
class ModelBatchingPolicy:
    """Deterministic request bounds shared by model-assisted extractors."""

    max_chars: int = 40_000
    max_passages: int = 32
    overlap_passages: int = 1

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("model batch max_chars must be positive")
        if self.max_passages <= 0:
            raise ValueError("model batch max_passages must be positive")
        if self.overlap_passages < 0:
            raise ValueError("model batch overlap_passages must be non-negative")
        if self.overlap_passages >= self.max_passages:
            raise ValueError("model batch overlap_passages must be less than max_passages")


def build_model_requests(
    document: Document,
    passages: tuple[Passage, ...],
    policy: ModelBatchingPolicy,
) -> tuple[ModelClaimRequest, ...]:
    model_passages = tuple(
        ModelPassage(
            passage_id=passage.passage_id,
            section_id=passage.section_id,
            ordinal=passage.ordinal,
            text=passage.text,
        )
        for passage in passages
    )
    batches: list[tuple[ModelPassage, ...]] = []
    start = 0
    while start < len(model_passages):
        batch: list[ModelPassage] = []
        char_count = 0
        cursor = start
        while cursor < len(model_passages) and len(batch) < policy.max_passages:
            passage = model_passages[cursor]
            next_count = char_count + len(passage.text)
            if batch and next_count > policy.max_chars:
                break
            batch.append(passage)
            char_count = next_count
            cursor += 1
        if not batch:
            raise RuntimeError("model batching failed to make progress")
        batches.append(tuple(batch))
        if cursor >= len(model_passages):
            break
        next_start = cursor - policy.overlap_passages
        start = max(start + 1, next_start)

    return tuple(
        ModelClaimRequest(
            document_id=document.document_id,
            title=document.title,
            passages=batch,
        )
        for batch in batches
    )


def validate_candidate_batch_scope(
    candidate: EvidenceGroundedCandidate,
    allowed_passage_ids: set[UUID],
    all_passage_ids: set[UUID],
) -> None:
    for selector in candidate.evidence:
        if selector.passage_id not in all_passage_ids:
            raise ValueError(f"model evidence references unknown passage: {selector.passage_id}")
        if selector.passage_id not in allowed_passage_ids:
            raise ValueError(
                f"model evidence references passage outside request batch: {selector.passage_id}"
            )
