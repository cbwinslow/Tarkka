"""Explicit orchestration for immutable retrieval-segment embedding derivations.

The service implements the embedding-indexing portion of the retrieval contract in
``docs/SIMILARITY_CONSENSUS_AND_GRAPH.md``. It deliberately receives both the
embedder and persistence adapter from its caller: model selection, downloads, and
transport configuration remain outside the application layer.
"""

from __future__ import annotations

from tarkka.domain.retrieval import RetrievalSegment
from tarkka.domain.retrieval_embeddings import SegmentEmbedding
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.ports.embedding_stores import EmbeddingStore
from tarkka.ports.embeddings import SegmentEmbedder


class EmbeddingIndexError(RuntimeError):
    """A provider or store failed while deriving one embedding index."""


class EmbeddingProvenanceError(EmbeddingIndexError):
    """An embedder returned a valid embedding for a different source segment."""


class EmbeddingIndexService:
    """Embed one exact retrieval projection through caller-selected adapters."""

    def __init__(self, *, embedder: SegmentEmbedder, embeddings: EmbeddingStore) -> None:
        self._embedder = embedder
        self._embeddings = embeddings

    def index(self, projection: RetrievalSegmentIndex) -> tuple[SegmentEmbedding, ...]:
        """Persist one immutable embedding derivation per segment in ``projection``.

        Already durable derivations are safe to encounter again because
        :class:`EmbeddingStore` writes by immutable embedding identity. A failed
        projection may therefore be retried without changing canonical source state
        or overwriting successful segment derivations.
        """
        if not isinstance(projection, RetrievalSegmentIndex):
            raise ValueError("embedding projection must be a RetrievalSegmentIndex")

        derived: list[SegmentEmbedding] = []
        for segment in projection.segments:
            embedding = self._embed(segment)
            self._validate_provenance(segment, embedding)
            self._persist(segment, embedding)
            derived.append(embedding)
        return tuple(derived)

    def _embed(self, segment: RetrievalSegment) -> SegmentEmbedding:
        try:
            return self._embedder.embed(segment)
        except Exception as exc:
            raise EmbeddingIndexError(
                f"embedding derivation failed for segment {segment.segment_id}"
            ) from exc

    def _persist(self, segment: RetrievalSegment, embedding: SegmentEmbedding) -> None:
        try:
            self._embeddings.put(embedding)
        except Exception as exc:
            raise EmbeddingIndexError(
                "embedding persistence failed for "
                f"segment {segment.segment_id} and model "
                f"{embedding.model_identifier}@{embedding.model_revision}"
            ) from exc

    @staticmethod
    def _validate_provenance(segment: RetrievalSegment, embedding: SegmentEmbedding) -> None:
        if not isinstance(embedding, SegmentEmbedding):
            raise EmbeddingProvenanceError(
                f"embedder returned a non-embedding result for segment {segment.segment_id}"
            )
        if (
            embedding.segment_id != segment.segment_id
            or embedding.segment_digest != segment.digest
            or embedding.segment_derivation_version != segment.derivation_version
            or embedding.segment_configuration_fingerprint
            != segment.configuration_fingerprint
        ):
            raise EmbeddingProvenanceError(
                "embedder returned mismatched provenance for "
                f"segment {segment.segment_id} and model "
                f"{embedding.model_identifier}@{embedding.model_revision}"
            )
