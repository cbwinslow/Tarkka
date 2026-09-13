"""Tests for bounded provenance-safe vector candidate retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import inf
from uuid import UUID, uuid4

import pytest

from tarkka.application.lexical_retrieval import RetrievalIndexNotFoundError
from tarkka.application.vector_retrieval import (
    MAX_VECTOR_CANDIDATE_LIMIT,
    VectorCandidateProvenanceError,
    VectorCandidateRetrievalError,
    VectorCandidateRetrievalService,
)
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import (
    EmbeddingNormalization,
    QueryEmbedding,
    SegmentEmbedding,
)
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.ports.vector_retrieval import VectorCandidate, VectorCandidateQuery

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000003590")


def _projection(configuration: str = "fixture-v1") -> RetrievalSegmentIndex:
    return RetrievalSegmentIndex(
        document_id=_DOCUMENT_ID,
        derivation_version="whole-passage-v1",
        configuration_fingerprint=configuration,
        segments=tuple(
            RetrievalSegment(
                document_id=_DOCUMENT_ID,
                text=text,
                source_spans=(
                    RetrievalPassageSpan(
                        UUID(int=3591 + ordinal), UUID(int=3601 + ordinal), 0, len(text)
                    ),
                ),
                derivation_version="whole-passage-v1",
                configuration_fingerprint=configuration,
            )
            for ordinal, text in enumerate(("first segment", "second segment"))
        ),
    )


def _embedding(
    segment: RetrievalSegment,
    *,
    model: str = "fixture-model",
    revision: str = "1",
    configuration: str = "model-fixture-v1",
) -> SegmentEmbedding:
    return SegmentEmbedding.for_segment(
        segment,
        model_identifier=model,
        model_revision=revision,
        configuration_fingerprint=configuration,
        normalization=EmbeddingNormalization.NONE,
        values=(float(len(segment.text)), 1.0),
    )


@dataclass
class _Indexes:
    projection: RetrievalSegmentIndex | None

    def replace(self, index: RetrievalSegmentIndex) -> None:
        self.projection = index

    def get(
        self, *, document_id: UUID, derivation_version: str, configuration_fingerprint: str
    ) -> RetrievalSegmentIndex | None:
        if self.projection is not None and (
            document_id,
            derivation_version,
            configuration_fingerprint,
        ) == (
            self.projection.document_id,
            self.projection.derivation_version,
            self.projection.configuration_fingerprint,
        ):
            return self.projection
        return None

    def list_for_document(self, document_id: UUID) -> tuple[RetrievalSegmentIndex, ...]:
        if self.projection is not None and self.projection.document_id == document_id:
            return (self.projection,)
        return ()


@dataclass
class _Embeddings:
    values: dict[UUID, SegmentEmbedding] = field(default_factory=dict)

    def put(self, embedding: SegmentEmbedding) -> None:
        self.values[embedding.embedding_id] = embedding

    def get(self, embedding_id: UUID) -> SegmentEmbedding | None:
        return self.values.get(embedding_id)

    def list_for_segment(self, segment_id: UUID) -> tuple[SegmentEmbedding, ...]:
        return tuple(item for item in self.values.values() if item.segment_id == segment_id)


@dataclass
class _Retriever:
    candidates: tuple[VectorCandidate, ...] = ()
    failure: Exception | None = None
    requests: list[VectorCandidateQuery] = field(default_factory=list)

    def search(self, query: VectorCandidateQuery) -> tuple[VectorCandidate, ...]:
        self.requests.append(query)
        if self.failure is not None:
            raise self.failure
        return self.candidates


def _service(
    projection: RetrievalSegmentIndex,
    embeddings: tuple[SegmentEmbedding, ...],
    retriever: _Retriever,
) -> VectorCandidateRetrievalService:
    return VectorCandidateRetrievalService(
        indexes=_Indexes(projection),
        embeddings=_Embeddings({item.embedding_id: item for item in embeddings}),
        retriever=retriever,
    )


def test_search_returns_deterministically_ranked_exact_segment_candidates() -> None:
    projection = _projection()
    query, second = tuple(_embedding(segment) for segment in projection.segments)
    retriever = _Retriever(
        candidates=(
            VectorCandidate(second.embedding_id, 0.5),
            VectorCandidate(query.embedding_id, 0.9),
        )
    )

    hits = _service(projection, (query, second), retriever).search(
        _DOCUMENT_ID,
        derivation_version="whole-passage-v1",
        configuration_fingerprint="fixture-v1",
        query_embedding_id=query.embedding_id,
        limit=2,
    )

    assert [hit.embedding.embedding_id for hit in hits] == [query.embedding_id, second.embedding_id]
    assert [hit.rank for hit in hits] == [1, 2]
    assert hits[1].segment.source_spans == projection.segments[1].source_spans
    assert retriever.requests[0].query_embedding == query


def test_search_accepts_an_explicit_non_source_query_embedding() -> None:
    projection = _projection()
    candidate = _embedding(projection.segments[1])
    query = QueryEmbedding.for_query(
        UUID(int=999),
        "independent user query",
        model_identifier="fixture-model",
        model_revision="1",
        configuration_fingerprint="model-fixture-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(3.0, 1.0),
    )
    retriever = _Retriever(candidates=(VectorCandidate(candidate.embedding_id, 0.5),))

    hits = _service(projection, (candidate,), retriever).search(
        _DOCUMENT_ID,
        derivation_version="whole-passage-v1",
        configuration_fingerprint="fixture-v1",
        query_embedding=query,
    )

    assert hits[0].segment == projection.segments[1]
    assert retriever.requests[0].query_embedding == query


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (object(), "embedding"),
        (
            lambda embedding: VectorCandidateQuery(
                embedding,
                "bad",
                "v1",
                "config",  # type: ignore[arg-type]
            ),
            "document_id",
        ),
        (lambda embedding: VectorCandidateQuery(embedding, _DOCUMENT_ID, "", "config"), "version"),
        (lambda embedding: VectorCandidateQuery(embedding, _DOCUMENT_ID, "v1", ""), "fingerprint"),
        (
            lambda embedding: VectorCandidateQuery(embedding, _DOCUMENT_ID, "v1", "config", 0),
            "limit",
        ),
    ],
)
def test_vector_candidate_query_rejects_invalid_contract_values(
    query: object, message: str
) -> None:
    embedding = _embedding(_projection().segments[0])
    with pytest.raises(ValueError, match=message):
        if callable(query):
            query(embedding)
        else:
            VectorCandidateQuery(query, _DOCUMENT_ID, "v1", "config")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("embedding_id", "score", "message"),
    [("bad", 0.1, "embedding_id"), (uuid4(), inf, "score"), (uuid4(), 1, "score")],
)
def test_vector_candidate_rejects_invalid_contract_values(
    embedding_id: object, score: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        VectorCandidate(embedding_id, score)  # type: ignore[arg-type]


def test_search_rejects_limits_and_a_missing_exact_projection() -> None:
    projection = _projection()
    query = _embedding(projection.segments[0])
    service = _service(projection, (query,), _Retriever())

    with pytest.raises(ValueError, match="must not exceed"):
        service.search(
            _DOCUMENT_ID,
            derivation_version="whole-passage-v1",
            configuration_fingerprint="fixture-v1",
            query_embedding_id=query.embedding_id,
            limit=MAX_VECTOR_CANDIDATE_LIMIT + 1,
        )
    with pytest.raises(RetrievalIndexNotFoundError):
        service.search(
            _DOCUMENT_ID,
            derivation_version="different-v1",
            configuration_fingerprint="fixture-v1",
            query_embedding_id=query.embedding_id,
        )
    with pytest.raises(ValueError, match="exactly one"):
        service.search(
            _DOCUMENT_ID,
            derivation_version="whole-passage-v1",
            configuration_fingerprint="fixture-v1",
        )


def test_search_rejects_unknown_or_cross_projection_query_embeddings() -> None:
    projection = _projection()
    query = _embedding(projection.segments[0])
    service = _service(projection, (), _Retriever())
    with pytest.raises(VectorCandidateRetrievalError, match="not found"):
        service.search(
            _DOCUMENT_ID,
            derivation_version="whole-passage-v1",
            configuration_fingerprint="fixture-v1",
            query_embedding_id=query.embedding_id,
        )

    other = _embedding(_projection("other-v1").segments[0])
    with pytest.raises(VectorCandidateProvenanceError, match="does not belong"):
        _service(projection, (other,), _Retriever()).search(
            _DOCUMENT_ID,
            derivation_version="whole-passage-v1",
            configuration_fingerprint="fixture-v1",
            query_embedding_id=other.embedding_id,
        )


def test_search_fails_closed_for_adapter_and_candidate_contract_failures() -> None:
    projection = _projection()
    query, second = tuple(_embedding(segment) for segment in projection.segments)
    cause = RuntimeError("fixture adapter unavailable")
    with pytest.raises(VectorCandidateRetrievalError, match="failed") as raised:
        _service(projection, (query, second), _Retriever(failure=cause)).search(
            _DOCUMENT_ID,
            derivation_version="whole-passage-v1",
            configuration_fingerprint="fixture-v1",
            query_embedding_id=query.embedding_id,
        )
    assert raised.value.__cause__ is cause

    for candidates, message, limit in (
        (
            (VectorCandidate(query.embedding_id, 0.1), VectorCandidate(second.embedding_id, 0.2)),
            "exceeded",
            1,
        ),
        (
            (VectorCandidate(query.embedding_id, 0.1), VectorCandidate(query.embedding_id, 0.2)),
            "duplicate",
            2,
        ),
        ((VectorCandidate(uuid4(), 0.1),), "unknown", 1),
    ):
        with pytest.raises(VectorCandidateRetrievalError, match=message):
            _service(projection, (query, second), _Retriever(candidates=candidates)).search(
                _DOCUMENT_ID,
                derivation_version="whole-passage-v1",
                configuration_fingerprint="fixture-v1",
                query_embedding_id=query.embedding_id,
                limit=limit,
            )


def test_search_rejects_a_candidate_with_a_different_model_contract() -> None:
    projection = _projection()
    query = _embedding(projection.segments[0])
    incompatible = _embedding(projection.segments[1], revision="different")
    with pytest.raises(VectorCandidateProvenanceError, match="incompatible"):
        _service(
            projection,
            (query, incompatible),
            _Retriever(candidates=(VectorCandidate(incompatible.embedding_id, 0.5),)),
        ).search(
            _DOCUMENT_ID,
            derivation_version="whole-passage-v1",
            configuration_fingerprint="fixture-v1",
            query_embedding_id=query.embedding_id,
        )
