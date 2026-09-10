from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.embedding_store import PostgresEmbeddingStore

pytestmark = [pytest.mark.integration, pytest.mark.external]


def _embedding(*, model_revision: str = "1") -> SegmentEmbedding:
    segment = RetrievalSegment(
        document_id=UUID(int=1),
        text="fixture",
        source_spans=(RetrievalPassageSpan(UUID(int=2), UUID(int=3), 0, 7),),
        derivation_version="v1",
        configuration_fingerprint="segment-v1",
    )
    return SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture",
        model_revision=model_revision,
        configuration_fingerprint="config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )


def test_postgres_embedding_store_round_trips_idempotently(
    tarkka_postgres_settings: PostgresSettings,
) -> None:
    with connect(tarkka_postgres_settings) as connection:
        connection.execute("TRUNCATE TABLE tarkka.retrieval_embedding")
    store = PostgresEmbeddingStore(tarkka_postgres_settings)
    first = _embedding()
    second = _embedding(model_revision="2")

    store.put(first)
    store.put(first)
    store.put(second)

    assert store.get(first.embedding_id) == first
    assert store.list_for_segment(first.segment_id) == (first, second)
