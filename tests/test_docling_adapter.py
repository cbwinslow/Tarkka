from __future__ import annotations

from pathlib import Path, PurePosixPath

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.docling_parser import DoclingParser


class _FakeDoclingDocument:
    name = "Normalized Research Paper"

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
        artifact_id=__import__("uuid").uuid4(),
        sha256="a" * 64,
        size_bytes=123,
        media_type="application/pdf",
        storage_key=PurePosixPath("aa/a" * 1),
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
    assert document.parser_version == "injected"
    assert document.title == "Normalized Research Paper"
    assert len(document.sections) == 2
    text = "".join(
        passage.text for section in document.sections for passage in section.passages
    )
    assert "\x00" not in text
    assert "\ufffd" in text
    assert {section.document_id for section in document.sections} == {document.document_id}
