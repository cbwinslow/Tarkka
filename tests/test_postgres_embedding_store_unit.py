from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.embedding_store import PostgresEmbeddingStore, _vector_values


def _embedding() -> SegmentEmbedding:
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
        model_revision="1",
        configuration_fingerprint="config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    rowcount: int = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        return None


def _row(value: SegmentEmbedding) -> tuple[Any, ...]:
    return (
        value.embedding_id,
        value.segment_id,
        value.segment_digest,
        value.segment_derivation_version,
        value.segment_configuration_fingerprint,
        value.model_identifier,
        value.model_revision,
        value.configuration_fingerprint,
        value.normalization.value,
        "[1,2]",
        value.dimension,
    )


def test_postgres_embedding_store_writes_idempotently_and_reads() -> None:
    embedding = _embedding()
    connection = _Connection([_Cursor(rowcount=1), _Cursor(row=_row(embedding))])
    store = PostgresEmbeddingStore(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )
    store.put(embedding)
    assert connection.calls[0][1][-2:] == ("[1.0,2.0]", embedding.dimension)
    assert store.get(embedding.embedding_id) == embedding


def test_postgres_embedding_store_rejects_conflicting_identity_and_lists_segment() -> None:
    embedding = _embedding()
    conflict = _Connection([_Cursor(rowcount=0), _Cursor(row=None)])
    store = PostgresEmbeddingStore(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: conflict
    )
    with pytest.raises(ValueError, match="conflicting embedding"):
        store.put(embedding)
    listing = _Connection([_Cursor(rows=[_row(embedding)])])
    store = PostgresEmbeddingStore(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: listing
    )
    assert store.list_for_segment(embedding.segment_id) == (embedding,)


def test_postgres_embedding_store_accepts_an_identical_concurrent_write() -> None:
    embedding = _embedding()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_row(embedding))])
    store = PostgresEmbeddingStore(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )

    store.put(embedding)


def test_postgres_embedding_store_rejects_invalid_vector_representation() -> None:
    with pytest.raises(ValueError, match="invalid PostgreSQL vector"):
        _vector_values("not-a-vector")
