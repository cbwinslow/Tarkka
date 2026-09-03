from __future__ import annotations

from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.domain.ocr_quality import QualityGateDecision, QualityGrade
from tarkka.domain.source_observations import Capability, ObservationBasis
from tarkka.infrastructure.storage import docling_parser
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


def test_docling_ocr_derivation_is_separate_and_conservatively_review_gated(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"not-a-real-pdf")
    artifact = _artifact()
    derivation = DoclingParser(converter=_FakeConverter()).derive(artifact, source)

    assert derivation.document.artifact_id == artifact.artifact_id
    assert derivation.quality_report.derivation_id == derivation.derivation_id
    assert derivation.quality_report.source_artifact_id == artifact.artifact_id
    assert derivation.quality_report.source_artifact_sha256 == artifact.sha256
    assert derivation.quality_report.grade is QualityGrade.UNKNOWN
    assert derivation.quality_report.gate_decision is QualityGateDecision.REQUIRE_REVIEW
    assert derivation.quality_report.pages == ()
    assert derivation.quality_report.warnings


def test_docling_ocr_derivation_has_distinct_stable_output_identity(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"not-a-real-pdf")
    artifact = _artifact()
    parser = DoclingParser(converter=_FakeConverter())

    native = parser.parse_native(artifact, source)
    first = parser.derive(artifact, source)
    second = parser.derive(artifact, source)

    assert first.derivation_id == second.derivation_id
    assert first.document.document_id == second.document.document_id
    assert first.document.document_id != native.document.document_id
    assert first.document.figures[0].figure_id != native.document.figures[0].figure_id
    assert first.document.tables[0].table_id != native.document.tables[0].table_id
    assert first.document.equations[0].equation_id != native.document.equations[0].equation_id


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


def test_docling_default_constructor_builds_converter_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converter = object()
    module = SimpleNamespace(DocumentConverter=lambda: converter)
    monkeypatch.setattr(docling_parser, "import_module", lambda _name: module)
    monkeypatch.setattr(docling_parser, "version", lambda _name: "9.9.9")

    parser = DoclingParser()

    assert parser._converter is converter
    assert parser.version == "9.9.9"


def test_docling_default_constructor_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> object:
        raise ImportError("synthetic missing docling")

    monkeypatch.setattr(docling_parser, "import_module", missing)

    with pytest.raises(RuntimeError, match="Docling is not installed") as exc_info:
        DoclingParser()

    assert isinstance(exc_info.value.__cause__, ImportError)


def test_docling_availability_and_extension_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docling_parser, "import_module", lambda _name: object())
    assert DoclingParser.is_available() is True

    artifact = Artifact(
        artifact_id=uuid4(),
        sha256="b" * 64,
        size_bytes=1,
        media_type="application/octet-stream",
        storage_key=PurePosixPath("bb/docling-extension"),
        original_name="paper.docx",
    )
    assert DoclingParser(converter=_FakeConverter()).supports(artifact) is True


def test_docling_helpers_handle_missing_and_non_string_values() -> None:
    document_id = uuid4()
    artifact_id = uuid4()
    blank_formula = SimpleNamespace(label="formula", text="   ", prov=())

    assert docling_parser._docling_equations(
        SimpleNamespace(texts=(blank_formula,)),
        document_id=document_id,
        artifact_id=artifact_id,
        identifier_scope="docling",
    ) == ()
    assert docling_parser._page_number(SimpleNamespace(prov=())) is None
    assert docling_parser._optional_text(123) == "123"
