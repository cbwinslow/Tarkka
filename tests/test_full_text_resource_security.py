from __future__ import annotations

from types import MappingProxyType

import pytest

from tarkka.ports.full_text import FullTextResource

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def _resource(**overrides: object) -> FullTextResource:
    values: dict[str, object] = {
        "provider": "fixture",
        "source_uri": "https://example.org/paper.txt",
        "media_type": "text/plain",
        "filename": "paper.txt",
        "metadata": {"source": "fixture"},
    }
    values.update(overrides)
    return FullTextResource(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider", " ", "provider must not be blank"),
        ("source_uri", " ", "source URI must not be blank"),
        ("media_type", " ", "media type must not be blank"),
        ("filename", " ", "filename must not be blank"),
    ],
)
def test_full_text_resource_rejects_blank_required_fields(
    field: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _resource(**{field: value})


@pytest.mark.parametrize(
    "filename",
    [
        ".",
        "..",
        "../paper.txt",
        "subdir/paper.txt",
        "/tmp/paper.txt",
        "..\\paper.txt",
        "subdir\\paper.txt",
        "C:\\temp\\paper.txt",
        "paper\x00.txt",
    ],
)
def test_full_text_resource_rejects_traversing_or_absolute_filenames(filename: str) -> None:
    with pytest.raises(ValueError, match="filename must be one safe path component"):
        _resource(filename=filename)


def test_full_text_resource_accepts_single_safe_component_and_freezes_metadata() -> None:
    resource = _resource(filename="paper-2026.08.txt")

    assert resource.filename == "paper-2026.08.txt"
    assert isinstance(resource.metadata, MappingProxyType)
    assert dict(resource.metadata) == {"source": "fixture"}
