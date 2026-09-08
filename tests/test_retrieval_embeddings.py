"""Contracts for provenance-safe retrieval embedding derivations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID

import pytest

from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.ports.embeddings import SegmentEmbedder


def _segment() -> RetrievalSegment:
    return RetrievalSegment(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        text="A provenance-safe segment.",
        source_spans=(
            RetrievalPassageSpan(
                UUID("00000000-0000-0000-0000-000000000002"),
                UUID("00000000-0000-0000-0000-000000000003"),
                0,
                26,
            ),
        ),
        derivation_version="whole-passage-v1",
        configuration_fingerprint="fixture-v1",
    )


@dataclass(frozen=True)
class _DeterministicEmbedder:
    model_identifier: str = "fixture-embedder"
    model_revision: str = "1"

    def embed(self, segment: RetrievalSegment) -> SegmentEmbedding:
        return SegmentEmbedding.for_segment(
            segment,
            model_identifier=self.model_identifier,
            model_revision=self.model_revision,
            configuration_fingerprint="fixture-config-v1",
            normalization=EmbeddingNormalization.L2,
            values=(0.6, 0.8),
        )


def test_embedding_retains_exact_segment_and_model_provenance() -> None:
    segment = _segment()

    embedding = SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-embedder",
        model_revision="2026-09-08",
        configuration_fingerprint="fixture-config-v1",
        normalization=EmbeddingNormalization.L2,
        values=(0.6, 0.8),
    )

    assert embedding.segment_id == segment.segment_id
    assert embedding.segment_digest == segment.digest
    assert embedding.segment_derivation_version == segment.derivation_version
    assert embedding.segment_configuration_fingerprint == segment.configuration_fingerprint
    assert embedding.dimension == 2
    assert embedding.values == (0.6, 0.8)


def test_embedding_identity_keeps_model_and_configuration_derivations_distinct() -> None:
    segment = _segment()
    baseline = SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-embedder",
        model_revision="1",
        configuration_fingerprint="fixture-config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )

    assert SegmentEmbedding.for_segment(
        segment,
        model_identifier="other-embedder",
        model_revision="1",
        configuration_fingerprint="fixture-config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    ).embedding_id != baseline.embedding_id
    assert SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-embedder",
        model_revision="2",
        configuration_fingerprint="fixture-config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    ).embedding_id != baseline.embedding_id
    assert SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-embedder",
        model_revision="1",
        configuration_fingerprint="fixture-config-v2",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    ).embedding_id != baseline.embedding_id


@pytest.mark.parametrize(
    ("values", "normalization", "message"),
    [
        ((), EmbeddingNormalization.NONE, "non-empty"),
        ((1.0, float("nan")), EmbeddingNormalization.NONE, "finite"),
        ((1.0, float("inf")), EmbeddingNormalization.NONE, "finite"),
        ((2.0, 0.0), EmbeddingNormalization.L2, "unit length"),
    ],
)
def test_embedding_rejects_invalid_vector_values(
    values: tuple[float, ...], normalization: EmbeddingNormalization, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SegmentEmbedding.for_segment(
            _segment(),
            model_identifier="fixture-embedder",
            model_revision="1",
            configuration_fingerprint="fixture-config-v1",
            normalization=normalization,
            values=values,
        )


def test_embedding_rejects_invalid_provenance_and_dimension() -> None:
    segment = _segment()
    valid = SegmentEmbedding.for_segment(
        segment,
        model_identifier="fixture-embedder",
        model_revision="1",
        configuration_fingerprint="fixture-config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )

    with pytest.raises(ValueError, match="model_identifier"):
        SegmentEmbedding(
            valid.embedding_id,
            valid.segment_id,
            valid.segment_digest,
            valid.segment_derivation_version,
            valid.segment_configuration_fingerprint,
            " ",
            valid.model_revision,
            valid.configuration_fingerprint,
            valid.normalization,
            valid.values,
            valid.dimension,
        )
    with pytest.raises(ValueError, match="dimension"):
        SegmentEmbedding(
            valid.embedding_id,
            valid.segment_id,
            valid.segment_digest,
            valid.segment_derivation_version,
            valid.segment_configuration_fingerprint,
            valid.model_identifier,
            valid.model_revision,
            valid.configuration_fingerprint,
            valid.normalization,
            valid.values,
            3,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"embedding_id": "not-a-uuid"}, "IDs"),
        ({"segment_digest": "short"}, "SHA-256"),
        ({"segment_digest": "g" * 64}, "SHA-256"),
        ({"normalization": "l2"}, "EmbeddingNormalization"),
        ({"embedding_id": UUID(int=99)}, "immutable embedding provenance"),
    ],
)
def test_embedding_rejects_invalid_identity_material(
    changes: dict[str, object], message: str
) -> None:
    valid = SegmentEmbedding.for_segment(
        _segment(),
        model_identifier="fixture-embedder",
        model_revision="1",
        configuration_fingerprint="fixture-config-v1",
        normalization=EmbeddingNormalization.NONE,
        values=(1.0, 2.0),
    )

    with pytest.raises(ValueError, match=message):
        replace(valid, **changes)


def test_embedding_rejects_non_segment_source() -> None:
    with pytest.raises(ValueError, match="RetrievalSegment"):
        SegmentEmbedding.for_segment(
            cast(RetrievalSegment, object()),
            model_identifier="fixture-embedder",
            model_revision="1",
            configuration_fingerprint="fixture-config-v1",
            normalization=EmbeddingNormalization.NONE,
            values=(1.0, 2.0),
        )


def test_deterministic_embedding_port_has_no_provider_specific_contract() -> None:
    embedder: SegmentEmbedder = _DeterministicEmbedder()

    assert embedder.embed(_segment()) == embedder.embed(_segment())
