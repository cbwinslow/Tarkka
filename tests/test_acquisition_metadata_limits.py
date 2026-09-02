from __future__ import annotations

import pytest

from tarkka.ports.acquisitions import (
    MAX_ACQUISITION_METADATA_ITEMS,
    MAX_ACQUISITION_METADATA_KEY_CHARS,
    MAX_ACQUISITION_METADATA_VALUE_CHARS,
    ArtifactCandidate,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_acquisition_metadata_accepts_exact_public_limits() -> None:
    metadata = {
        "k" * MAX_ACQUISITION_METADATA_KEY_CHARS: (
            "v" * MAX_ACQUISITION_METADATA_VALUE_CHARS
        ),
        **{
            f"key-{index}": "value"
            for index in range(MAX_ACQUISITION_METADATA_ITEMS - 1)
        },
    }

    candidate = ArtifactCandidate(source_uri="custom://source", metadata=metadata)

    assert len(candidate.metadata) == MAX_ACQUISITION_METADATA_ITEMS


def test_acquisition_metadata_rejects_too_many_items() -> None:
    metadata = {
        f"key-{index}": "value"
        for index in range(MAX_ACQUISITION_METADATA_ITEMS + 1)
    }

    with pytest.raises(ValueError, match="must contain at most"):
        ArtifactCandidate(source_uri="custom://source", metadata=metadata)


def test_acquisition_metadata_rejects_oversized_key() -> None:
    with pytest.raises(ValueError, match="keys must not exceed"):
        ArtifactCandidate(
            source_uri="custom://source",
            metadata={"k" * (MAX_ACQUISITION_METADATA_KEY_CHARS + 1): "value"},
        )


def test_acquisition_metadata_rejects_oversized_value() -> None:
    with pytest.raises(ValueError, match="values must not exceed"):
        ArtifactCandidate(
            source_uri="custom://source",
            metadata={"key": "v" * (MAX_ACQUISITION_METADATA_VALUE_CHARS + 1)},
        )
