"""Offline exact-handle metrics for deterministic hybrid retrieval rankings."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GoldRetrievalQuery:
    """Explicit relevant segment handles for one reproducible evaluation query."""

    query_id: UUID
    relevant_segment_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, UUID):
            raise ValueError("gold retrieval query_id must be a UUID")
        if any(not isinstance(item, UUID) for item in self.relevant_segment_ids):
            raise ValueError("gold retrieval relevance must be a UUID tuple")
        if len(set(self.relevant_segment_ids)) != len(self.relevant_segment_ids):
            raise ValueError("gold retrieval relevance must not contain duplicates")


@dataclass(frozen=True, slots=True)
class RankedRetrievalQuery:
    """Ordered exact segment handles produced for one evaluation query."""

    query_id: UUID
    segment_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, UUID):
            raise ValueError("ranked retrieval query_id must be a UUID")
        if any(not isinstance(item, UUID) for item in self.segment_ids):
            raise ValueError("ranked retrieval segment IDs must be UUIDs")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("ranked retrieval segment IDs must not contain duplicates")


@dataclass(frozen=True, slots=True)
class RetrievalQueryEvaluation:
    """Inspectable exact-handle ranking metrics for one query."""

    query_id: UUID
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    relevant_retrieved: int


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    """Aggregate and query-level retrieval metrics without opaque score collapse."""

    query_reports: tuple[RetrievalQueryEvaluation, ...]
    mean_reciprocal_rank: float
    mean_precision_at_k: float
    mean_recall_at_k: float
    limit: int


def evaluate_retrieval(
    ranked: tuple[RankedRetrievalQuery, ...],
    gold: tuple[GoldRetrievalQuery, ...],
    *,
    limit: int,
) -> RetrievalEvaluationReport:
    """Evaluate ordered exact handles against explicit reproducible relevance sets."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("retrieval evaluation limit must be a positive integer")
    _unique_query_ids(ranked, "ranked")
    _unique_query_ids(gold, "gold")
    gold_by_query = {item.query_id: item for item in gold}
    if set(item.query_id for item in ranked) != set(gold_by_query):
        raise ValueError("ranked and gold retrieval query IDs must match exactly")
    reports = tuple(
        _evaluate_query(item, gold_by_query[item.query_id], limit) for item in ranked
    )
    count = len(reports)
    return RetrievalEvaluationReport(
        query_reports=reports,
        mean_reciprocal_rank=(
            sum(item.reciprocal_rank for item in reports) / count if count else 0.0
        ),
        mean_precision_at_k=(
            sum(item.precision_at_k for item in reports) / count if count else 0.0
        ),
        mean_recall_at_k=(sum(item.recall_at_k for item in reports) / count if count else 0.0),
        limit=limit,
    )


def _unique_query_ids(items: tuple[object, ...], label: str) -> None:
    identifiers = [
        item.query_id
        for item in items
        if isinstance(item, (GoldRetrievalQuery, RankedRetrievalQuery))
    ]
    if len(identifiers) != len(items) or len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{label} retrieval queries must have unique UUID IDs")


def _evaluate_query(
    ranked: RankedRetrievalQuery, gold: GoldRetrievalQuery, limit: int
) -> RetrievalQueryEvaluation:
    predicted = ranked.segment_ids[:limit]
    relevant = set(gold.relevant_segment_ids)
    matches = [segment_id for segment_id in predicted if segment_id in relevant]
    first_rank = next(
        (index for index, item in enumerate(predicted, start=1) if item in relevant), None
    )
    return RetrievalQueryEvaluation(
        query_id=ranked.query_id,
        precision_at_k=len(matches) / len(predicted) if predicted else 0.0,
        recall_at_k=len(matches) / len(relevant) if relevant else 0.0,
        reciprocal_rank=1.0 / first_rank if first_rank is not None else 0.0,
        relevant_retrieved=len(matches),
    )
