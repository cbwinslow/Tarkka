"""Immutable, provenance-safe vector derivations for retrieval segments."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.retrieval import RetrievalSegment


class EmbeddingNormalization(StrEnum):
    """Declared vector normalization applied by an embedding provider."""

    NONE = "none"
    L2 = "l2"


@dataclass(frozen=True, slots=True)
class SegmentEmbedding:
    """One immutable vector derivation tied to an exact retrieval segment."""

    embedding_id: UUID
    segment_id: UUID
    segment_digest: str
    segment_derivation_version: str
    segment_configuration_fingerprint: str
    model_identifier: str
    model_revision: str
    configuration_fingerprint: str
    normalization: EmbeddingNormalization
    values: tuple[float, ...]
    dimension: int

    def __post_init__(self) -> None:
        if not isinstance(self.embedding_id, UUID) or not isinstance(self.segment_id, UUID):
            raise ValueError("embedding and segment IDs must be UUIDs")
        if not isinstance(self.segment_digest, str) or len(self.segment_digest) != 64:
            raise ValueError("embedding segment_digest must be a SHA-256 digest")
        try:
            int(self.segment_digest, 16)
        except ValueError as exc:
            raise ValueError("embedding segment_digest must be a SHA-256 digest") from exc
        for name, value in (
            ("segment_derivation_version", self.segment_derivation_version),
            ("segment_configuration_fingerprint", self.segment_configuration_fingerprint),
            ("model_identifier", self.model_identifier),
            ("model_revision", self.model_revision),
            ("configuration_fingerprint", self.configuration_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"embedding {name} must not be blank")
        if not isinstance(self.normalization, EmbeddingNormalization):
            raise ValueError("embedding normalization must be an EmbeddingNormalization")
        if not isinstance(self.values, tuple) or not self.values:
            raise ValueError("embedding values must be a non-empty tuple")
        if any(
            not isinstance(value, float) or not math.isfinite(value) for value in self.values
        ):
            raise ValueError("embedding values must be finite floats")
        if (
            not isinstance(self.dimension, int)
            or isinstance(self.dimension, bool)
            or self.dimension != len(self.values)
        ):
            raise ValueError("embedding dimension must match vector length")
        if self.normalization is EmbeddingNormalization.L2 and not math.isclose(
            math.fsum(value * value for value in self.values), 1.0, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise ValueError("L2-normalized embedding values must have unit length")
        if self.embedding_id != _embedding_id(self):
            raise ValueError("embedding_id must match immutable embedding provenance")

    @classmethod
    def for_segment(
        cls,
        segment: RetrievalSegment,
        *,
        model_identifier: str,
        model_revision: str,
        configuration_fingerprint: str,
        normalization: EmbeddingNormalization,
        values: tuple[float, ...],
    ) -> SegmentEmbedding:
        """Create a vector derivation from one exact immutable retrieval segment."""
        if not isinstance(segment, RetrievalSegment):
            raise ValueError("embedding source must be a RetrievalSegment")
        provisional = cls.__new__(cls)
        object.__setattr__(provisional, "segment_id", segment.segment_id)
        object.__setattr__(provisional, "segment_digest", segment.digest)
        object.__setattr__(provisional, "segment_derivation_version", segment.derivation_version)
        object.__setattr__(
            provisional, "segment_configuration_fingerprint", segment.configuration_fingerprint
        )
        object.__setattr__(provisional, "model_identifier", model_identifier)
        object.__setattr__(provisional, "model_revision", model_revision)
        object.__setattr__(provisional, "configuration_fingerprint", configuration_fingerprint)
        object.__setattr__(provisional, "normalization", normalization)
        object.__setattr__(provisional, "values", values)
        object.__setattr__(provisional, "dimension", len(values))
        return cls(
            embedding_id=_embedding_id(provisional),
            segment_id=segment.segment_id,
            segment_digest=segment.digest,
            segment_derivation_version=segment.derivation_version,
            segment_configuration_fingerprint=segment.configuration_fingerprint,
            model_identifier=model_identifier,
            model_revision=model_revision,
            configuration_fingerprint=configuration_fingerprint,
            normalization=normalization,
            values=values,
            dimension=len(values),
        )


def _embedding_id(embedding: SegmentEmbedding) -> UUID:
    """Return a deterministic identifier for immutable embedding identity material."""
    payload = {
        "configuration_fingerprint": embedding.configuration_fingerprint,
        "model_identifier": embedding.model_identifier,
        "model_revision": embedding.model_revision,
        "normalization": embedding.normalization.value,
        "segment_configuration_fingerprint": embedding.segment_configuration_fingerprint,
        "segment_derivation_version": embedding.segment_derivation_version,
        "segment_digest": embedding.segment_digest,
        "segment_id": str(embedding.segment_id),
        "values": embedding.values,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return uuid5(NAMESPACE_URL, f"tarkka:retrieval-embedding:{digest}")
