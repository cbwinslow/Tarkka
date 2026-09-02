from __future__ import annotations

import pytest

from tarkka.domain.path_safety import is_safe_filename_component, portable_filename_component
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
        ("bad\x1fname.pdf", False),
        ("bad\x7fname.pdf", False),
        ("paper\u2028name.pdf", False),
        ("paper\u202ename.pdf", False),
        ("dir/paper.pdf", False),
        (r"dir\paper.pdf", False),
        ("paper.pdf:metadata", False),
        ("paper.pdf.", False),
        ("CON", False),
        ("con.txt", False),
        ("COM1", False),
        ("Lpt9.csv", False),
        ("CON .txt", False),
        ("x" * 241, False),
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("semantic/scholar-paper:123.pdf", "semantic_scholar-paper_123.pdf"),
        ("CON", "CON_"),
        ("report. ", "report"),
        ("CON .txt", "CON_.txt"),
        ("\x00", "_"),
    ],
)
def test_portable_filename_component_canonicalizes_hostile_generated_text(
    value: str, expected: str
) -> None:
    actual = portable_filename_component(value)

    assert actual == expected
    assert is_safe_filename_component(actual)


def test_portable_filename_component_validates_inputs_and_uses_fallback_for_blank_source() -> None:
    assert portable_filename_component("", fallback="download.bin") == "download.bin"

    with pytest.raises(ValueError, match="source must be a string"):
        portable_filename_component(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fallback must be safe"):
        portable_filename_component("paper.pdf", fallback="CON")


def test_portable_filename_component_replaces_display_controls_and_bounds_long_names() -> None:
    assert portable_filename_component("paper\u202ename\u2028.pdf") == "paper_name_.pdf"

    filename = portable_filename_component(f"{'x' * 500}.pdf")

    assert filename.endswith(".pdf")
    assert len(filename.encode("utf-8")) <= 240
    assert len(filename.encode("utf-16-le")) // 2 <= 240
    assert is_safe_filename_component(filename)

    long_extension_filename = portable_filename_component(f"paper.{'x' * 500}")

    assert long_extension_filename.startswith("paper-")
    assert is_safe_filename_component(long_extension_filename)
