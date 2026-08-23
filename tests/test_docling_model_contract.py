from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.docling_parser import DoclingParser

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _Label:
    def __init__(self, value: object) -> None:
        self.value = value


class _Prov:
    def __init__(self, page_no: object) -> None:
        self.page_no = page_no


class _TextItem:
    def __init__(self, label: object, text: object, page_no: object = 1) -> None:
        self.label = label
        self.text = text
        self.prov = (_Prov(page_no),)


class _TableData:
    def __init__(self, rows: object, cols: object) -> None:
        self.num_rows = rows
        self.num_cols = cols


class _Table:
    def __init__(self, rows: object, cols: object, page_no: object = 1) -> None:
        self.label = "table"
        self.caption = None
        self.data = _TableData(rows, cols)
        self.prov = (_Prov(page_no),)


class _Document:
    name = "Contract Fixture"
    pictures: tuple[object, ...] = ()

    def __init__(
        self,
        *,
        texts: tuple[object, ...] = (),
        tables: tuple[object, ...] = (),
    ) -> None:
        self.texts = texts
        self.tables = tables

    def export_to_markdown(self) -> str:
        return "# Contract\nBody.\n"


class _Result:
    def __init__(self, document: object) -> None:
        self.document = document


class _Converter:
    def __init__(self, document: object) -> None:
        self.document = document

    def convert(self, source: Path) -> _Result:
        assert source.name == "paper.pdf"
        return _Result(self.document)


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="7" * 64,
        size_bytes=123,
        media_type="application/pdf",
        storage_key=PurePosixPath("77/docling-contract"),
        original_name="paper.pdf",
    )


def _parse(tmp_path: Path, document: object):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fixture")
    parser = DoclingParser(converter=_Converter(document))
    return parser.parse_native(_artifact(), source)


def test_docling_formula_signal_accepts_official_enum_value(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        _Document(texts=(_TextItem(_Label("formula"), "x = y", 3),)),
    )

    assert len(result.document.equations) == 1
    equation = result.document.equations[0]
    assert equation.source_text == "x = y"
    assert equation.page_number == 3


@pytest.mark.parametrize("label", ["formula", "FORMULA", "Formula", " formula "])
def test_docling_formula_signal_accepts_normalized_string_values(
    tmp_path: Path,
    label: str,
) -> None:
    result = _parse(tmp_path, _Document(texts=(_TextItem(label, "a + b"),)))

    assert [item.source_text for item in result.document.equations] == ["a + b"]


@pytest.mark.parametrize(
    "label",
    [
        "equation",
        "not_formula",
        "formula_caption",
        "text",
        None,
        7,
        "   ",
        _Label(123),
    ],
)
def test_docling_formula_signal_rejects_label_lookalikes(
    tmp_path: Path,
    label: object,
) -> None:
    result = _parse(tmp_path, _Document(texts=(_TextItem(label, "not an equation"),)))

    assert result.document.equations == ()


def test_docling_optional_structural_fields_degrade_without_inventing_values(
    tmp_path: Path,
) -> None:
    result = _parse(
        tmp_path,
        _Document(
            texts=(_TextItem(_Label("formula"), "x", 0),),
            tables=(_Table(-1, "three", 0),),
        ),
    )

    equation = result.document.equations[0]
    table = result.document.tables[0]
    assert equation.page_number is None
    assert table.page_number is None
    assert table.row_count is None
    assert table.column_count is None


def test_docling_missing_optional_collections_are_empty(tmp_path: Path) -> None:
    class _MinimalDocument:
        name = "Minimal"

        def export_to_markdown(self) -> str:
            return "Body.\n"

    result = _parse(tmp_path, _MinimalDocument())

    assert result.document.figures == ()
    assert result.document.tables == ()
    assert result.document.equations == ()
