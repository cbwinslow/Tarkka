"""Tests for offline exact-handle hybrid retrieval evaluation."""

from __future__ import annotations

from uuid import UUID

import pytest

import tarkka.evaluation as evaluation_package
from tarkka.evaluation.retrieval import (
    GoldRetrievalQuery,
    RankedRetrievalQuery,
    evaluate_retrieval,
)

_QUERY_ONE = UUID(int=1)
_QUERY_TWO = UUID(int=2)
_SEGMENT_ONE = UUID(int=11)
_SEGMENT_TWO = UUID(int=12)
_SEGMENT_THREE = UUID(int=13)


def test_evaluation_reports_exact_handle_metrics_per_query_and_in_aggregate() -> None:
    report = evaluate_retrieval(
        ranked=(
            RankedRetrievalQuery(_QUERY_ONE, (_SEGMENT_THREE, _SEGMENT_ONE)),
            RankedRetrievalQuery(_QUERY_TWO, (_SEGMENT_THREE,)),
        ),
        gold=(
            GoldRetrievalQuery(_QUERY_ONE, (_SEGMENT_ONE, _SEGMENT_TWO)),
            GoldRetrievalQuery(_QUERY_TWO, (_SEGMENT_THREE,)),
        ),
        limit=2,
    )

    first, second = report.query_reports
    assert (first.precision_at_k, first.recall_at_k, first.reciprocal_rank) == (0.5, 0.5, 0.5)
    assert (second.precision_at_k, second.recall_at_k, second.reciprocal_rank) == (1.0, 1.0, 1.0)
    assert report.mean_reciprocal_rank == 0.75
    assert report.mean_precision_at_k == 0.75
    assert report.mean_recall_at_k == 0.75


def test_evaluation_has_explicit_empty_prediction_and_gold_behavior() -> None:
    report = evaluate_retrieval(
        ranked=(RankedRetrievalQuery(_QUERY_ONE, ()),),
        gold=(GoldRetrievalQuery(_QUERY_ONE, ()),),
        limit=1,
    )

    assert report.query_reports[0].relevant_retrieved == 0
    assert report.query_reports[0].precision_at_k == 0.0
    assert report.query_reports[0].recall_at_k == 0.0
    assert report.query_reports[0].reciprocal_rank == 0.0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: GoldRetrievalQuery("bad", ()), "query_id"),  # type: ignore[arg-type]
        (lambda: GoldRetrievalQuery(_QUERY_ONE, ("bad",)), "UUID"),  # type: ignore[arg-type]
        (lambda: GoldRetrievalQuery(_QUERY_ONE, (_SEGMENT_ONE, _SEGMENT_ONE)), "duplicates"),
        (lambda: RankedRetrievalQuery("bad", ()), "query_id"),  # type: ignore[arg-type]
        (lambda: RankedRetrievalQuery(_QUERY_ONE, ("bad",)), "UUID"),  # type: ignore[arg-type]
        (lambda: RankedRetrievalQuery(_QUERY_ONE, (_SEGMENT_ONE, _SEGMENT_ONE)), "duplicates"),
    ],
)
def test_query_contracts_reject_invalid_handles(factory: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()  # type: ignore[operator]


def test_evaluation_rejects_invalid_limits_and_query_sets() -> None:
    ranked = RankedRetrievalQuery(_QUERY_ONE, ())
    gold = GoldRetrievalQuery(_QUERY_ONE, ())
    with pytest.raises(ValueError, match="limit"):
        evaluate_retrieval((ranked,), (gold,), limit=0)
    with pytest.raises(ValueError, match="match exactly"):
        evaluate_retrieval((ranked,), (GoldRetrievalQuery(_QUERY_TWO, ()),), limit=1)
    with pytest.raises(ValueError, match="unique"):
        evaluate_retrieval((ranked, ranked), (gold,), limit=1)
    with pytest.raises(ValueError, match="unique"):
        evaluate_retrieval((ranked,), (gold, gold), limit=1)


def test_evaluation_rejects_malformed_query_objects_and_exports_api() -> None:
    with pytest.raises(ValueError, match="unique"):
        evaluate_retrieval((object(),), (), limit=1)  # type: ignore[arg-type]
    assert evaluation_package.evaluate_retrieval is evaluate_retrieval
