"""Durable storage boundary for immutable retrieval embedding derivations."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.retrieval_embeddings import SegmentEmbedding


class EmbeddingStore(Protocol):
    """Store and retrieve immutable embedding derivations by exact identity."""

    def put(self, embedding: SegmentEmbedding) -> None: ...

    def get(self, embedding_id: UUID) -> SegmentEmbedding | None: ...

    def list_for_segment(self, segment_id: UUID) -> tuple[SegmentEmbedding, ...]: ...
