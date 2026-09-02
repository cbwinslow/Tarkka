from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import pytest

from tarkka.ports.full_text import FullTextResource

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def _resource(
    *,
    provider: str = "fixture",
    source_uri: str = "https://example.org/paper.txt",
    media_type: str = "text/plain",
    filename: str = "paper.txt",
    metadata: Mapping[str, str] | None = None,
) -> FullTextResource:
    return FullTextResource(
        provider=provider,
        source_uri=source_uri,
        media_type=media_type,
        filename=filename,
        metadata={"source": "fixture"} if metadata is None else metadata,
    )


def test_full_text_resource_rejects_blank_provider() -> None:
    with pytest.raises(ValueError, match="provider must not be blank"):
        _resource(provider=" ")


def test_full_text_resource_rejects_blank_source_uri() -> None:
    with pytest.raises(ValueError, match="source URI must not be blank"):
        _resource(source_uri=" ")


def test_full_text_resource_rejects_blank_media_type() -> None:
    with pytest.raises(ValueError, match="media type must not be blank"):
        _resource(media_type=" ")


def test_full_text_resource_rejects_blank_filename() -> None:
    with pytest.raises(ValueError, match="filename must not be blank"):
        _resource(filename=" ")


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
        "paper.txt:metadata",
        "paper.txt.",
        "NUL",
        "LPT1.csv",
    ],
)
def test_full_text_resource_rejects_nonportable_filenames(filename: str) -> None:
    with pytest.raises(ValueError, match="filename must be one safe path component"):
        _resource(filename=filename)


def test_full_text_resource_accepts_single_safe_component_and_freezes_metadata() -> None:
    resource = _resource(filename="paper-2026.08.txt")

    assert resource.filename == "paper-2026.08.txt"
    assert isinstance(resource.metadata, MappingProxyType)
    assert dict(resource.metadata) == {"source": "fixture"}
