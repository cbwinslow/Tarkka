"""Optional local Sentence Transformers adapter for immutable retrieval segments."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from math import fsum, sqrt
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

from tarkka.domain.retrieval import RetrievalSegment
from tarkka.domain.retrieval_embeddings import (
    EmbeddingNormalization,
    QueryEmbedding,
    SegmentEmbedding,
)


class SentenceTransformerUnavailableError(RuntimeError):
    """Raised when the optional local embedding runtime is unavailable."""


class _SentenceTransformerModel(Protocol):
    def encode(self, sentences: str, *, normalize_embeddings: bool) -> Iterable[object]: ...


@dataclass(frozen=True, slots=True)
class LocalSentenceTransformerEmbedder:
    """Embed exact segments with a caller-pinned local model and explicit provenance."""

    model: _SentenceTransformerModel
    model_identifier: str
    model_revision: str
    configuration_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("model_identifier", self.model_identifier),
            ("model_revision", self.model_revision),
            ("configuration_fingerprint", self.configuration_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"local embedding {name} must be non-blank")

    @classmethod
    def from_local_path(
        cls,
        path: Path,
        *,
        model_identifier: str,
        model_revision: str,
        configuration_fingerprint: str,
    ) -> LocalSentenceTransformerEmbedder:
        """Load only already-downloaded model files; never allow a network fallback."""
        local_path = path.expanduser().resolve()
        if not local_path.is_dir():
            raise ValueError("local embedding model path must be an existing directory")
        try:
            module = import_module("sentence_transformers")
            constructor = cast(Any, module.SentenceTransformer)
        except ImportError as exc:
            raise SentenceTransformerUnavailableError(
                "install the tarkka embeddings extra to use local sentence-transformer embeddings"
            ) from exc
        try:
            model = constructor(str(local_path), local_files_only=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SentenceTransformerUnavailableError(
                "unable to load the pinned local sentence-transformer model"
            ) from exc
        return cls(model, model_identifier, model_revision, configuration_fingerprint)

    def embed(self, segment: RetrievalSegment) -> SegmentEmbedding:
        """Create a normalized immutable embedding for one exact source-backed segment."""
        if not isinstance(segment, RetrievalSegment):
            raise ValueError("local embedding source must be a RetrievalSegment")
        values = self._encode(segment.text, f"segment {segment.segment_id}")
        return SegmentEmbedding.for_segment(
            segment,
            model_identifier=self.model_identifier,
            model_revision=self.model_revision,
            configuration_fingerprint=self.configuration_fingerprint,
            normalization=EmbeddingNormalization.L2,
            values=values,
        )

    def embed_query(self, query_id: UUID, text: str) -> QueryEmbedding:
        """Embed external query text without representing it as a source segment."""
        values = self._encode(text, f"query {query_id}")
        return QueryEmbedding.for_query(
            query_id,
            text,
            model_identifier=self.model_identifier,
            model_revision=self.model_revision,
            configuration_fingerprint=self.configuration_fingerprint,
            normalization=EmbeddingNormalization.L2,
            values=values,
        )

    def _encode(self, text: str, label: str) -> tuple[float, ...]:
        try:
            raw_values = self.model.encode(text, normalize_embeddings=True)
            return _l2_normalize(tuple(float(value) for value in cast(Iterable[Any], raw_values)))
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            raise SentenceTransformerUnavailableError(
                f"local embedding failed for {label}"
            ) from exc


def _l2_normalize(values: tuple[float, ...]) -> tuple[float, ...]:
    """Normalize float32 provider output again for Tarkka's exact double-precision contract."""
    norm = sqrt(fsum(value * value for value in values))
    if norm == 0.0:
        raise ValueError("local embedding model returned a zero vector")
    return tuple(value / norm for value in values)
