from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.infrastructure.json_embedding_store import JsonEmbeddingStore


def _embedding(*, model_revision: str = "1", configuration: str = "fixture-v1") -> SegmentEmbedding:
    segment = RetrievalSegment(
        document_id=UUID(int=1),
        text="Embedding fixture.",
        source_spans=(RetrievalPassageSpan(UUID(int=2), UUID(int=3), 0, 18),),
        derivation_version="whole-passage-v1",
        configuration_fingerprint="segment-fixture-v1",
    )
    return SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-embedder",
        model_revision=model_revision,
        configuration_fingerprint=configuration,
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )


def test_json_embedding_store_round_trips_and_lists_derivations(tmp_path: Path) -> None:
    path = tmp_path / "embeddings.json"
    store = JsonEmbeddingStore(path)
    first = _embedding()
    second = _embedding(model_revision="2", configuration="fixture-v2")

    store.put(first)
    store.put(first)
    store.put(second)

    assert store.get(first.embedding_id) == first
    assert store.list_for_segment(first.segment_id) == (first, second)
    assert JsonEmbeddingStore(path).get(first.embedding_id) == first


def test_json_embedding_store_rejects_a_distinct_payload_with_the_same_identity(
    tmp_path: Path,
) -> None:
    store = JsonEmbeddingStore(tmp_path / "embeddings.json")
    first = _embedding()
    collision = _embedding(model_revision="2")
    object.__setattr__(collision, "embedding_id", first.embedding_id)
    store.put(first)

    with pytest.raises(RuntimeError, match="identity collision"):
        store.put(collision)


def test_json_embedding_store_fails_closed_for_corrupt_catalog(tmp_path: Path) -> None:
    path = tmp_path / "embeddings.json"
    store = JsonEmbeddingStore(path)
    embedding = _embedding()
    store.put(embedding)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unable to read embedding catalog"):
        store.get(embedding.embedding_id)
