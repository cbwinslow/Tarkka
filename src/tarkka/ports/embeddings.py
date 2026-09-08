"""Replaceable embedding boundary for immutable retrieval segments."""

from __future__ import annotations

from typing import Protocol

from tarkka.domain.retrieval import RetrievalSegment
from tarkka.domain.retrieval_embeddings import SegmentEmbedding


class SegmentEmbedder(Protocol):
    """Produce one provenance-complete embedding for an exact retrieval segment."""

    def embed(self, segment: RetrievalSegment) -> SegmentEmbedding: ...
