"""Candidate-only vector retrieval over exact persisted projections."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.application.lexical_retrieval import RetrievalIndexNotFoundError
from tarkka.domain.retrieval import RetrievalSegment
from tarkka.domain.retrieval_embeddings import SegmentEmbedding
from tarkka.ports.embedding_stores import EmbeddingStore
from tarkka.ports.retrieval_indexes import RetrievalSegmentStore
from tarkka.ports.vector_retrieval import (
    VectorCandidate,
    VectorCandidateQuery,
    VectorCandidateRetriever,
)

MAX_VECTOR_CANDIDATE_LIMIT = 100


class VectorCandidateRetrievalError(RuntimeError):
    """Vector candidate retrieval failed without changing source state."""


class VectorCandidateProvenanceError(VectorCandidateRetrievalError):
    """A persisted or returned candidate cannot belong to the requested projection."""


@dataclass(frozen=True, slots=True)
class VectorRetrievalHit:
    """A scored vector candidate retaining exact segment and embedding provenance."""

    segment: RetrievalSegment
    embedding: SegmentEmbedding
    score: float
    rank: int


class VectorCandidateRetrievalService:
    """Return bounded, provenance-safe vector candidates from one exact projection."""

    def __init__(
        self,
        *,
        indexes: RetrievalSegmentStore,
        embeddings: EmbeddingStore,
        retriever: VectorCandidateRetriever,
    ) -> None:
        self._indexes = indexes
        self._embeddings = embeddings
        self._retriever = retriever

    def search(
        self,
        document_id: UUID,
        *,
        derivation_version: str,
        configuration_fingerprint: str,
        query_embedding_id: UUID,
        limit: int = 10,
    ) -> tuple[VectorRetrievalHit, ...]:
        """Return candidates without mixing projection or model derivations."""
        if limit > MAX_VECTOR_CANDIDATE_LIMIT:
            raise ValueError(
                f"vector candidate query limit must not exceed {MAX_VECTOR_CANDIDATE_LIMIT}"
            )
        projection = self._indexes.get(
            document_id=document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )
        if projection is None:
            raise RetrievalIndexNotFoundError(
                document_id,
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
            )
        query_embedding = self._embeddings.get(query_embedding_id)
        if query_embedding is None:
            raise VectorCandidateRetrievalError(
                f"embedding derivation not found: {query_embedding_id}"
            )
        segments = {segment.segment_id: segment for segment in projection.segments}
        query_segment = segments.get(query_embedding.segment_id)
        if query_segment is None or not _matches_segment(query_embedding, query_segment):
            raise VectorCandidateProvenanceError(
                f"query embedding does not belong to requested projection: {query_embedding_id}"
            )
        request = VectorCandidateQuery(
            query_embedding=query_embedding,
            document_id=document_id,
            segment_derivation_version=derivation_version,
            segment_configuration_fingerprint=configuration_fingerprint,
            limit=limit,
        )
        try:
            candidates = self._retriever.search(request)
        except Exception as exc:
            raise VectorCandidateRetrievalError(
                f"vector candidate retrieval failed for embedding {query_embedding_id}"
            ) from exc
        return self._hits(candidates, segments, query_embedding, limit)

    def _hits(
        self,
        candidates: tuple[VectorCandidate, ...],
        segments: dict[UUID, RetrievalSegment],
        query_embedding: SegmentEmbedding,
        limit: int,
    ) -> tuple[VectorRetrievalHit, ...]:
        if len(candidates) > limit:
            raise VectorCandidateRetrievalError(
                "vector retriever exceeded requested candidate limit"
            )
        if len({candidate.embedding_id for candidate in candidates}) != len(candidates):
            raise VectorCandidateRetrievalError(
                "vector retriever returned duplicate embedding candidates"
            )
        resolved: list[tuple[VectorCandidate, SegmentEmbedding, RetrievalSegment]] = []
        for candidate in candidates:
            embedding = self._embeddings.get(candidate.embedding_id)
            if embedding is None:
                raise VectorCandidateProvenanceError(
                    f"vector retriever returned an unknown embedding: {candidate.embedding_id}"
                )
            segment = segments.get(embedding.segment_id)
            if segment is None or not _matches_segment(embedding, segment) or not _matches_model(
                embedding, query_embedding
            ):
                raise VectorCandidateProvenanceError(
                    f"vector retriever returned incompatible embedding: {candidate.embedding_id}"
                )
            resolved.append((candidate, embedding, segment))
        return tuple(
            VectorRetrievalHit(
                segment=segment,
                embedding=embedding,
                score=candidate.score,
                rank=rank,
            )
            for rank, (candidate, embedding, segment) in enumerate(
                sorted(
                    resolved,
                    key=lambda item: (-item[0].score, str(item[0].embedding_id)),
                ),
                start=1,
            )
        )


def _matches_segment(embedding: SegmentEmbedding, segment: RetrievalSegment) -> bool:
    """Return whether one immutable embedding belongs to exactly one segment."""
    return (
        embedding.segment_id == segment.segment_id
        and embedding.segment_digest == segment.digest
        and embedding.segment_derivation_version == segment.derivation_version
        and embedding.segment_configuration_fingerprint == segment.configuration_fingerprint
    )


def _matches_model(candidate: SegmentEmbedding, query: SegmentEmbedding) -> bool:
    """Return whether candidate and query use the same vector derivation contract."""
    return (
        candidate.model_identifier == query.model_identifier
        and candidate.model_revision == query.model_revision
        and candidate.configuration_fingerprint == query.configuration_fingerprint
        and candidate.normalization == query.normalization
        and candidate.dimension == query.dimension
    )
