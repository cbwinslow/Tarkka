"""PostgreSQL pgvector persistence for immutable embedding derivations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID

from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)
from tarkka.ports.embedding_stores import EmbeddingStore


class PostgresEmbeddingStore(EmbeddingStore):
    """Persist immutable embedding identities through PostgreSQL and pgvector."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connection_factory: ConnectionFactory = connect,
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def put(self, embedding: SegmentEmbedding) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.retrieval_embedding (
                    embedding_id, segment_id, segment_digest, segment_derivation_version,
                    segment_configuration_fingerprint, model_identifier, model_revision,
                    configuration_fingerprint, normalization, embedding, dimension
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (embedding_id) DO NOTHING
                """,
                _params(embedding),
            )
            if cursor.rowcount == 0:
                existing = self._get(connection, embedding.embedding_id)
                if existing != embedding:
                    raise ValueError(f"conflicting embedding: {embedding.embedding_id}")

    def get(self, embedding_id: UUID) -> SegmentEmbedding | None:
        with self._connection() as connection:
            return self._get(connection, embedding_id)

    def list_for_segment(self, segment_id: UUID) -> tuple[SegmentEmbedding, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT embedding_id, segment_id, segment_digest, segment_derivation_version,
                       segment_configuration_fingerprint, model_identifier, model_revision,
                       configuration_fingerprint, normalization, embedding::text, dimension
                FROM tarkka.retrieval_embedding
                WHERE segment_id = %s
                ORDER BY model_identifier, model_revision, configuration_fingerprint, embedding_id
                """,
                (segment_id,),
            ).fetchall()
            return tuple(_from_row(row) for row in rows)

    @staticmethod
    def _get(connection: Any, embedding_id: UUID) -> SegmentEmbedding | None:
        row = connection.execute(
            """
            SELECT embedding_id, segment_id, segment_digest, segment_derivation_version,
                   segment_configuration_fingerprint, model_identifier, model_revision,
                   configuration_fingerprint, normalization, embedding::text, dimension
            FROM tarkka.retrieval_embedding WHERE embedding_id = %s
            """,
            (embedding_id,),
        ).fetchone()
        return _from_row(row) if row is not None else None

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(self._settings, connection_factory=self._connect) as connection:
            yield connection


def _params(embedding: SegmentEmbedding) -> tuple[object, ...]:
    return (
        embedding.embedding_id,
        embedding.segment_id,
        embedding.segment_digest,
        embedding.segment_derivation_version,
        embedding.segment_configuration_fingerprint,
        embedding.model_identifier,
        embedding.model_revision,
        embedding.configuration_fingerprint,
        embedding.normalization.value,
        _vector_literal(embedding.values),
        embedding.dimension,
    )


def _from_row(row: tuple[Any, ...]) -> SegmentEmbedding:
    return SegmentEmbedding(
        embedding_id=cast(UUID, row[0]),
        segment_id=cast(UUID, row[1]),
        segment_digest=cast(str, row[2]),
        segment_derivation_version=cast(str, row[3]),
        segment_configuration_fingerprint=cast(str, row[4]),
        model_identifier=cast(str, row[5]),
        model_revision=cast(str, row[6]),
        configuration_fingerprint=cast(str, row[7]),
        normalization=EmbeddingNormalization(cast(str, row[8])),
        values=_vector_values(cast(str, row[9])),
        dimension=cast(int, row[10]),
    )


def _vector_literal(values: tuple[float, ...]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def _vector_values(value: str) -> tuple[float, ...]:
    if not value.startswith("[") or not value.endswith("]"):
        raise ValueError("invalid PostgreSQL vector representation")
    return tuple(float(item) for item in value[1:-1].split(",") if item)
