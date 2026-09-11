"""Tests for explicit immutable embedding-index orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest

from tarkka.application.embedding_index import (
    EmbeddingIndexError,
    EmbeddingIndexService,
    EmbeddingProvenanceError,
)
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.domain.retrieval_index import RetrievalSegmentIndex


def _projection(configuration: str = "fixture-v1") -> RetrievalSegmentIndex:
    document_id = UUID("00000000-0000-0000-0000-000000003400")
    return RetrievalSegmentIndex(
        document_id=document_id,
        derivation_version="whole-passage-v1",
        configuration_fingerprint=configuration,
        segments=tuple(
            RetrievalSegment(
                document_id=document_id,
                text=text,
                source_spans=(
                    RetrievalPassageSpan(
                        UUID(int=3401 + ordinal), UUID(int=3411 + ordinal), 0, len(text)
                    ),
                ),
                derivation_version="whole-passage-v1",
                configuration_fingerprint=configuration,
            )
            for ordinal, text in enumerate(("first fixture", "second fixture"))
        ),
    )


@dataclass
class _Embedder:
    calls: list[UUID] = field(default_factory=list)
    failure: Exception | None = None
    non_embedding: bool = False
    wrong_segment: RetrievalSegment | None = None

    def embed(self, segment: RetrievalSegment) -> SegmentEmbedding:
        self.calls.append(segment.segment_id)
        if self.failure is not None:
            raise self.failure
        if self.non_embedding:
            return object()  # type: ignore[return-value]
        source = self.wrong_segment or segment
        return SegmentEmbedding.for_segment(
            source,
            model_identifier="fixture-embedder",
            model_revision="1",
            configuration_fingerprint="fixture-model-v1",
            normalization=EmbeddingNormalization.NONE,
            values=(float(len(source.text)), 1.0),
        )


@dataclass
class _Embeddings:
    stored: dict[UUID, SegmentEmbedding] = field(default_factory=dict)
    failure: Exception | None = None
    failure_at: int | None = None
    put_calls: int = 0

    def put(self, embedding: SegmentEmbedding) -> None:
        self.put_calls += 1
        if self.failure is not None and self.put_calls == self.failure_at:
            raise self.failure
        existing = self.stored.setdefault(embedding.embedding_id, embedding)
        if existing != embedding:
            raise RuntimeError("embedding identity collision")

    def get(self, embedding_id: UUID) -> SegmentEmbedding | None:
        return self.stored.get(embedding_id)

    def list_for_segment(self, segment_id: UUID) -> tuple[SegmentEmbedding, ...]:
        return tuple(item for item in self.stored.values() if item.segment_id == segment_id)


def test_index_persists_one_complete_embedding_per_exact_projection_segment() -> None:
    projection = _projection()
    embedder = _Embedder()
    store = _Embeddings()

    derived = EmbeddingIndexService(embedder=embedder, embeddings=store).index(projection)

    assert tuple(embedder.calls) == tuple(segment.segment_id for segment in projection.segments)
    assert tuple(item.segment_id for item in derived) == tuple(
        segment.segment_id for segment in projection.segments
    )
    assert all(
        item.segment_digest == segment.digest
        for item, segment in zip(derived, projection.segments, strict=True)
    )
    assert all(item.segment_derivation_version == projection.derivation_version for item in derived)
    assert all(
        item.segment_configuration_fingerprint == projection.configuration_fingerprint
        for item in derived
    )
    assert tuple(store.stored.values()) == derived


def test_repeat_indexing_is_idempotent_and_projection_derivations_remain_distinct() -> None:
    projection = _projection()
    store = _Embeddings()
    service = EmbeddingIndexService(embedder=_Embedder(), embeddings=store)

    first = service.index(projection)
    second = service.index(projection)
    alternate = service.index(_projection("alternate-segment-fixture-v1"))

    assert second == first
    assert len(store.stored) == len(first) + len(alternate)
    assert {item.segment_configuration_fingerprint for item in store.stored.values()} == {
        "fixture-v1",
        "alternate-segment-fixture-v1",
    }


def test_index_rejects_a_non_projection_input() -> None:
    with pytest.raises(ValueError, match="RetrievalSegmentIndex"):
        EmbeddingIndexService(embedder=_Embedder(), embeddings=_Embeddings()).index(object())  # type: ignore[arg-type]


def test_index_preserves_the_embedder_failure_context() -> None:
    projection = _projection()
    cause = RuntimeError("fixture provider unavailable")

    with pytest.raises(EmbeddingIndexError, match=str(projection.segments[0].segment_id)) as raised:
        EmbeddingIndexService(embedder=_Embedder(failure=cause), embeddings=_Embeddings()).index(
            projection
        )

    assert raised.value.__cause__ is cause


def test_index_rejects_embedding_provenance_for_a_different_segment() -> None:
    projection = _projection()

    with pytest.raises(EmbeddingProvenanceError, match=str(projection.segments[0].segment_id)):
        EmbeddingIndexService(
            embedder=_Embedder(wrong_segment=projection.segments[1]), embeddings=_Embeddings()
        ).index(projection)


def test_index_rejects_a_non_embedding_result() -> None:
    projection = _projection()

    with pytest.raises(EmbeddingProvenanceError, match="non-embedding"):
        EmbeddingIndexService(
            embedder=_Embedder(non_embedding=True), embeddings=_Embeddings()
        ).index(projection)


def test_index_preserves_durable_derivations_when_the_store_fails_later() -> None:
    projection = _projection()
    cause = RuntimeError("fixture store unavailable")
    store = _Embeddings(failure=cause, failure_at=2)
    service = EmbeddingIndexService(embedder=_Embedder(), embeddings=store)

    with pytest.raises(EmbeddingIndexError, match="fixture-embedder@1") as raised:
        service.index(projection)

    assert raised.value.__cause__ is cause
    assert tuple(store.stored) == (SegmentEmbedding.for_segment(
        projection.segments[0],
        model_identifier="fixture-embedder",
        model_revision="1",
        configuration_fingerprint="fixture-model-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(float(len(projection.segments[0].text)), 1.0),
    ).embedding_id,)
    assert len(service.index(projection)) == len(projection.segments)
    assert len(store.stored) == len(projection.segments)
