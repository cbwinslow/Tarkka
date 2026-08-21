from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import Capability, ObservationBasis
from tarkka.infrastructure.storage.docling_parser import DoclingParser


class _Prov:
    page_no = 2


class _Picture:
    label = "Figure A"
    caption = "A reconstructed plot"
    prov = (_Prov(),)


class _TableData:
    num_rows = 4
    num_cols = 3


class _Table:
    label = "Table A"
    caption = "A reconstructed table"
    data = _TableData()
    prov = (_Prov(),)


class _Formula:
    label = "formula"
    text = "y = a + bx"
    prov = (_Prov(),)


class _FakeDoclingDocument:
    name = "Normalized Research Paper"
    pictures = (_Picture(),)
    tables = (_Table(),)
    texts = (_Formula(),)

    def export_to_markdown(self) -> str:
        return "# Abstract\nEvidence\x00 survives safely.\n\n## Methods\nRegression model.\n"


class _FakeConversionResult:
    document = _FakeDoclingDocument()


class _FakeConverter:
    def convert(self, source: Path) -> _FakeConversionResult:
        assert source.name == "paper.pdf"
        return _FakeConversionResult()


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="a" * 64,
        size_bytes=123,
        media_type="application/pdf",
        storage_key=PurePosixPath("aa/digest"),
        original_name="paper.pdf",
    )


def test_docling_adapter_normalizes_to_tarkka_document(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"not-a-real-pdf")
    artifact = _artifact()
    parser = DoclingParser(converter=_FakeConverter())

    document = parser.parse(artifact, source)

    assert parser.supports(artifact)
    assert document.artifact_id == artifact.artifact_id
    assert document.parser_name == "docling"
    assert document.parser_version == parser.version
    assert document.parser_version
    assert document.title == "Normalized Research Paper"
    assert len(document.sections) == 2
    text = "".join(
        passage.text for section in document.sections for passage in section.passages
    )
    assert "\x00" not in text
    assert "\ufffd" in text
    assert {section.document_id for section in document.sections} == {document.document_id}


def test_docling_native_parse_preserves_first_class_structural_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"not-a-real-pdf")
    parser = DoclingParser(converter=_FakeConverter())

    result = parser.parse_native(_artifact(), source)
    document = result.document

    assert len(document.figures) == 1
    assert document.figures[0].label == "Figure A"
    assert document.figures[0].caption == "A reconstructed plot"
    assert document.figures[0].page_number == 2

    assert len(document.tables) == 1
    assert document.tables[0].row_count == 4
    assert document.tables[0].column_count == 3

    assert len(document.equations) == 1
    assert document.equations[0].source_text == "y = a + bx"
    assert result.observation.basis is ObservationBasis.RECONSTRUCTED
    assert result.observation.metadata["counts"] == {
        "figures": 1,
        "tables": 1,
        "equations": 1,
        "sections": 2,
    }
    assert parser.manifest.supports(
        Capability.DOCUMENT_STRUCTURE,
        Capability.FIGURES,
        Capability.TABLES,
        Capability.EQUATIONS,
    )


def test_docling_ids_are_stable_for_same_artifact(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"not-a-real-pdf")
    parser = DoclingParser(converter=_FakeConverter())
    artifact = _artifact()

    first = parser.parse_native(artifact, source).document
    second = parser.parse_native(artifact, source).document

    assert first.document_id == second.document_id
    assert [section.section_id for section in first.sections] == [
        section.section_id for section in second.sections
    ]
    assert first.figures[0].figure_id == second.figures[0].figure_id
    assert first.tables[0].table_id == second.tables[0].table_id
    assert first.equations[0].equation_id == second.equations[0].equation_id
