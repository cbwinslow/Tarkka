from __future__ import annotations

import pytest

from tarkka.domain.path_safety import is_safe_filename_component
from tarkka.ports.acquisitions import AcquiredArtifact, ArtifactCandidate

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (123, False),
        ("", False),
        ("   ", False),
        (" paper.pdf", False),
        ("paper.pdf ", False),
        (".", False),
        ("..", False),
        ("bad\x00name.pdf", False),
        ("dir/paper.pdf", False),
        (r"dir\paper.pdf", False),
        ("paper.pdf", True),
    ],
)
def test_filename_component_safety_is_cross_platform(value: object, expected: bool) -> None:
    assert is_safe_filename_component(value) is expected


def test_acquisition_candidate_rejects_path_like_filename_hint() -> None:
    with pytest.raises(ValueError, match="filename hint must be one safe path component"):
        ArtifactCandidate(
            source_uri="file:///tmp/paper.pdf",
            filename_hint="../paper.pdf",
        )


def test_acquisition_receipt_rejects_path_like_filename() -> None:
    with pytest.raises(ValueError, match="filename must be one safe path component"):
        AcquiredArtifact(
            requested_uri="https://example.test/paper",
            final_uri="https://example.test/paper",
            size_bytes=0,
            sha256="0" * 64,
            filename=r"C:\temp\paper.pdf",
        )
