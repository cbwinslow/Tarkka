"""Replaceable bounded vector-candidate retrieval boundary."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from uuid import UUID

from tarkka.domain.retrieval_embeddings import SegmentEmbedding


@dataclass(frozen=True, slots=True)
class VectorCandidateQuery:
    """One bounded vector lookup scoped to an exact retrieval projection."""

    query_embedding: SegmentEmbedding
    document_id: UUID
    segment_derivation_version: str
    segment_configuration_fingerprint: str
    limit: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.query_embedding, SegmentEmbedding):
            raise ValueError("vector candidate query requires a SegmentEmbedding")
        if not isinstance(self.document_id, UUID):
            raise ValueError("vector candidate query document_id must be a UUID")
        for name, value in (
            ("segment_derivation_version", self.segment_derivation_version),
            ("segment_configuration_fingerprint", self.segment_configuration_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"vector candidate query {name} must not be blank")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError("vector candidate query limit must be a positive integer")


@dataclass(frozen=True, slots=True)
class VectorCandidate:
    """One adapter-scored immutable embedding handle before source mapping."""

    embedding_id: UUID
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.embedding_id, UUID):
            raise ValueError("vector candidate embedding_id must be a UUID")
        if not isinstance(self.score, float) or not isfinite(self.score):
            raise ValueError("vector candidate score must be a finite float")


class VectorCandidateRetriever(Protocol):
    """Find bounded scored embedding candidates through a replaceable adapter."""

    def search(self, query: VectorCandidateQuery) -> tuple[VectorCandidate, ...]: ...
