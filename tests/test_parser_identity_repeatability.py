from __future__ import annotations

from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from uuid import UUID

import pytest

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.docling_parser import DoclingParser
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000597")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000598")


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="5" * 64,
        size_bytes=7,
        media_type="application/pdf",
        storage_key=PurePosixPath("55/parser-id-repeatability"),
        original_name="paper.pdf",
    )


def _document_identity(document: object) -> tuple[object, ...]:
    sections = document.sections
    return (
        document.document_id,
        tuple(
            (
                section.section_id,
                tuple(passage.passage_id for passage in section.passages),
            )
            for section in sections
        ),
    )


def test_markdown_normalization_repeats_section_and_passage_ids() -> None:
    markdown = "# Methods\n\nFirst paragraph.\n\nSecond paragraph.\n"

    first = document_from_markdown(
        artifact=_artifact(),
        text=markdown,
        parser_name="fixture",
        parser_version="1",
        document_id=_DOCUMENT_ID,
    )
    second = document_from_markdown(
        artifact=_artifact(),
        text=markdown,
        parser_name="fixture",
        parser_version="1",
        document_id=_DOCUMENT_ID,
    )

    assert _document_identity(first) == _document_identity(second)


def test_docling_repeated_parse_preserves_document_observation_and_passage_ids(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fixture")

    class _Document:
        name = "Repeatability Fixture"
        pictures: tuple[object, ...] = ()
        tables: tuple[object, ...] = ()
        texts: tuple[object, ...] = ()

        def export_to_markdown(self) -> str:
            return "# Results\n\nStable body.\n"

    class _Converter:
        def convert(self, path: Path) -> object:
            assert path == source
            return SimpleNamespace(document=_Document())

    parser = DoclingParser(converter=_Converter())

    first = parser.parse_native(_artifact(), source)
    second = parser.parse_native(_artifact(), source)

    assert _document_identity(first.document) == _document_identity(second.document)
    assert first.observation.observation_id == second.observation.observation_id
    assert tuple(item.figure_id for item in first.document.figures) == tuple(
        item.figure_id for item in second.document.figures
    )
    assert tuple(item.table_id for item in first.document.tables) == tuple(
        item.table_id for item in second.document.tables
    )
    assert tuple(item.equation_id for item in first.document.equations) == tuple(
        item.equation_id for item in second.document.equations
    )
