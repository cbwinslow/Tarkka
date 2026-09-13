"""Tests for deterministic provenance-safe hybrid candidate fusion."""

from __future__ import annotations

from math import inf
from uuid import UUID

import pytest

from tarkka.application.hybrid_retrieval import (
    MAX_HYBRID_RETRIEVAL_LIMIT,
    HybridCandidateRetrievalService,
    HybridRetrievalProvenanceError,
    HybridRetrievalQuery,
)
from tarkka.application.vector_retrieval import VectorRetrievalHit
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.ports.retrieval import LexicalRetrievalHit


def _segment(number: int, text: str = "fixture") -> RetrievalSegment:
    return RetrievalSegment(
        document_id=UUID(int=1),
        text=text,
        source_spans=(RetrievalPassageSpan(UUID(int=2), UUID(int=number), 0, len(text)),),
        derivation_version="whole-passage-v1",
        configuration_fingerprint="fixture-v1",
    )


def _vector(segment: RetrievalSegment, *, score: float = 0.5, rank: int = 1) -> VectorRetrievalHit:
    embedding = SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-model",
        model_revision="1",
        configuration_fingerprint="model-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )
    return VectorRetrievalHit(segment, embedding, score, rank)


def _lexical(
    segment: RetrievalSegment, *, score: float = 1.0, rank: int = 1
) -> LexicalRetrievalHit:
    return LexicalRetrievalHit(segment, score, rank)


def test_fuse_preserves_lexical_vector_and_overlapping_provenance() -> None:
    first, second, third = _segment(10), _segment(11), _segment(12)
    hits = HybridCandidateRetrievalService().fuse(
        lexical_hits=(_lexical(first, rank=1), _lexical(second, rank=2)),
        vector_hits=(_vector(first, rank=2), _vector(third, rank=1)),
        query=HybridRetrievalQuery(),
    )

    assert [hit.segment for hit in hits] == [first, third, second]
    assert [hit.rank for hit in hits] == [1, 2, 3]
    assert hits[0].lexical_hit is not None and hits[0].vector_hit is not None
    assert hits[1].lexical_hit is None and hits[1].vector_hit is not None
    assert hits[2].lexical_hit is not None and hits[2].vector_hit is None


def test_fuse_uses_stable_segment_id_order_for_equal_scores_and_limit() -> None:
    first, second = _segment(20), _segment(21)
    hits = HybridCandidateRetrievalService().fuse(
        lexical_hits=(_lexical(second), _lexical(first)),
        vector_hits=(),
        query=HybridRetrievalQuery(vector_weight=0.0, limit=1),
    )

    assert hits == (hits[0],)
    assert hits[0].segment.segment_id == min(first.segment_id, second.segment_id, key=str)


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (lambda: HybridRetrievalQuery(lexical_weight=-1.0), "weight"),
        (lambda: HybridRetrievalQuery(vector_weight=inf), "weight"),
        (lambda: HybridRetrievalQuery(lexical_weight=0.0, vector_weight=0.0), "positive"),
        (lambda: HybridRetrievalQuery(limit=0), "limit"),
    ],
)
def test_query_validates_weights_and_limit(query: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        query()  # type: ignore[operator]


def test_fuse_rejects_invalid_query_and_over_limit() -> None:
    service = HybridCandidateRetrievalService()
    with pytest.raises(ValueError, match="HybridRetrievalQuery"):
        service.fuse(lexical_hits=(), vector_hits=(), query=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not exceed"):
        service.fuse(
            lexical_hits=(),
            vector_hits=(),
            query=HybridRetrievalQuery(limit=MAX_HYBRID_RETRIEVAL_LIMIT + 1),
        )


def test_fuse_fails_closed_for_duplicate_and_incompatible_hits() -> None:
    first, second = _segment(30), _segment(31)
    service = HybridCandidateRetrievalService()
    with pytest.raises(HybridRetrievalProvenanceError, match="duplicate"):
        service.fuse(
            lexical_hits=(_lexical(first), _lexical(first, rank=2)),
            vector_hits=(),
            query=HybridRetrievalQuery(),
        )
    with pytest.raises(HybridRetrievalProvenanceError, match="duplicate"):
        service.fuse(
            lexical_hits=(),
            vector_hits=(_vector(first), _vector(first, rank=2)),
            query=HybridRetrievalQuery(),
        )
    first_copy = _segment(32)
    object.__setattr__(first_copy, "segment_id", first.segment_id)
    with pytest.raises(HybridRetrievalProvenanceError, match="disagree"):
        service.fuse(
            lexical_hits=(_lexical(first),),
            vector_hits=(_vector(first_copy),),
            query=HybridRetrievalQuery(),
        )
    assert second.segment_id != first.segment_id


def test_fuse_rejects_malformed_hit_values_and_vector_provenance() -> None:
    segment = _segment(40)
    service = HybridCandidateRetrievalService()
    with pytest.raises(HybridRetrievalProvenanceError, match="lexical"):
        service.fuse(lexical_hits=(object(),), vector_hits=(), query=HybridRetrievalQuery())  # type: ignore[arg-type]
    with pytest.raises(HybridRetrievalProvenanceError, match="vector"):
        service.fuse(lexical_hits=(), vector_hits=(object(),), query=HybridRetrievalQuery())  # type: ignore[arg-type]
    malformed = _vector(segment)
    object.__setattr__(malformed, "score", 1)
    with pytest.raises(HybridRetrievalProvenanceError, match="invalid"):
        service.fuse(lexical_hits=(), vector_hits=(malformed,), query=HybridRetrievalQuery())
