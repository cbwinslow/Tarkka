"""Deterministic candidate-only fusion for lexical and vector retrieval hits."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from tarkka.application.vector_retrieval import VectorRetrievalHit
from tarkka.domain.retrieval import RetrievalSegment
from tarkka.ports.retrieval import LexicalRetrievalHit

MAX_HYBRID_RETRIEVAL_LIMIT = 100


class HybridRetrievalProvenanceError(ValueError):
    """A supplied retrieval hit cannot safely participate in exact-segment fusion."""


@dataclass(frozen=True, slots=True)
class HybridRetrievalQuery:
    """Explicit bounded weights for deterministic reciprocal-rank fusion."""

    lexical_weight: float = 1.0
    vector_weight: float = 1.0
    limit: int = 10

    def __post_init__(self) -> None:
        for name, value in (
            ("lexical_weight", self.lexical_weight),
            ("vector_weight", self.vector_weight),
        ):
            if not isinstance(value, float) or not isfinite(value) or value < 0.0:
                raise ValueError(f"hybrid retrieval {name} must be a finite non-negative float")
        if self.lexical_weight == 0.0 and self.vector_weight == 0.0:
            raise ValueError("hybrid retrieval requires at least one positive modality weight")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError("hybrid retrieval limit must be a positive integer")


@dataclass(frozen=True, slots=True)
class HybridRetrievalHit:
    """One fused candidate with explicit source and modality provenance."""

    segment: RetrievalSegment
    score: float
    rank: int
    lexical_hit: LexicalRetrievalHit | None
    vector_hit: VectorRetrievalHit | None


class HybridCandidateRetrievalService:
    """Fuse bounded exact-segment candidates without asserting semantic decisions."""

    def fuse(
        self,
        *,
        lexical_hits: tuple[LexicalRetrievalHit, ...],
        vector_hits: tuple[VectorRetrievalHit, ...],
        query: HybridRetrievalQuery,
    ) -> tuple[HybridRetrievalHit, ...]:
        """Return deterministic reciprocal-rank candidates with retained modality evidence."""
        if not isinstance(query, HybridRetrievalQuery):
            raise ValueError("hybrid retrieval query must be a HybridRetrievalQuery")
        if query.limit > MAX_HYBRID_RETRIEVAL_LIMIT:
            raise ValueError(
                f"hybrid retrieval limit must not exceed {MAX_HYBRID_RETRIEVAL_LIMIT}"
            )
        lexical = self._lexical_by_segment(lexical_hits)
        vector = self._vector_by_segment(vector_hits)
        combined: list[HybridRetrievalHit] = []
        for segment_id in lexical.keys() | vector.keys():
            lexical_hit = lexical.get(segment_id)
            vector_hit = vector.get(segment_id)
            if lexical_hit is not None:
                segment = lexical_hit.segment
            else:
                assert vector_hit is not None
                segment = vector_hit.segment
            if lexical_hit is not None and vector_hit is not None and not _same_segment(
                lexical_hit.segment, vector_hit.segment
            ):
                raise HybridRetrievalProvenanceError(
                    f"retrieval modalities disagree on segment provenance: {segment_id}"
                )
            score = (
                (query.lexical_weight / lexical_hit.rank if lexical_hit is not None else 0.0)
                + (query.vector_weight / vector_hit.rank if vector_hit is not None else 0.0)
            )
            combined.append(
                HybridRetrievalHit(
                    segment=segment,
                    score=score,
                    rank=0,
                    lexical_hit=lexical_hit,
                    vector_hit=vector_hit,
                )
            )
        return tuple(
            HybridRetrievalHit(
                segment=hit.segment,
                score=hit.score,
                rank=rank,
                lexical_hit=hit.lexical_hit,
                vector_hit=hit.vector_hit,
            )
            for rank, hit in enumerate(
                sorted(
                    combined,
                    key=lambda item: (-item.score, str(item.segment.segment_id)),
                )[: query.limit],
                start=1,
            )
        )

    @staticmethod
    def _lexical_by_segment(
        hits: tuple[LexicalRetrievalHit, ...],
    ) -> dict[UUID, LexicalRetrievalHit]:
        if not all(isinstance(hit, LexicalRetrievalHit) for hit in hits):
            raise HybridRetrievalProvenanceError("hybrid lexical hits must be LexicalRetrievalHit")
        by_segment = {hit.segment.segment_id: hit for hit in hits}
        if len(by_segment) != len(hits):
            raise HybridRetrievalProvenanceError("hybrid lexical hits contain duplicate segments")
        return by_segment

    @staticmethod
    def _vector_by_segment(
        hits: tuple[VectorRetrievalHit, ...],
    ) -> dict[UUID, VectorRetrievalHit]:
        if not all(isinstance(hit, VectorRetrievalHit) for hit in hits):
            raise HybridRetrievalProvenanceError("hybrid vector hits must be VectorRetrievalHit")
        by_segment = {hit.segment.segment_id: hit for hit in hits}
        if len(by_segment) != len(hits):
            raise HybridRetrievalProvenanceError("hybrid vector hits contain duplicate segments")
        for hit in hits:
            if (
                not isinstance(hit.segment, RetrievalSegment)
                or not isinstance(hit.score, float)
                or not isfinite(hit.score)
                or not isinstance(hit.rank, int)
                or isinstance(hit.rank, bool)
                or hit.rank < 1
                or hit.embedding.segment_id != hit.segment.segment_id
                or hit.embedding.segment_digest != hit.segment.digest
                or hit.embedding.segment_derivation_version != hit.segment.derivation_version
                or hit.embedding.segment_configuration_fingerprint
                != hit.segment.configuration_fingerprint
            ):
                raise HybridRetrievalProvenanceError(
                    "hybrid vector hit has invalid segment provenance"
                )
        return by_segment


def _same_segment(left: RetrievalSegment, right: RetrievalSegment) -> bool:
    """Return whether two modality hits retain exactly one derived segment identity."""
    return (
        left.segment_id == right.segment_id
        and left.digest == right.digest
        and left.derivation_version == right.derivation_version
        and left.configuration_fingerprint == right.configuration_fingerprint
    )
