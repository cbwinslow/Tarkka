from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.parsing import DocumentParser


def _assert_document_contract(document: Document, artifact: Artifact) -> None:
    assert document.artifact_id == artifact.artifact_id
    assert document.parser_name
    assert document.parser_version
    assert document.sections
    assert [section.ordinal for section in document.sections] == list(range(len(document.sections)))
    for section in document.sections:
        assert section.document_id == document.document_id
        for passage in section.passages:
            assert passage.document_id == document.document_id
            assert passage.section_id == section.section_id
            assert passage.char_end - passage.char_start == len(passage.text)


def _exercise(parser: DocumentParser, artifact: Artifact, path: Path) -> None:
    assert parser.supports(artifact)
    _assert_document_contract(parser.parse(artifact, path), artifact)


def test_plain_text_parser_satisfies_document_parser_contract(tmp_path: Path) -> None:
    source = tmp_path / "research.md"
    source.write_text("# Abstract\nEvidence.\n\n## Methods\nRegression.\n", encoding="utf-8")
    artifact = Artifact(
        artifact_id=uuid4(),
        sha256="b" * 64,
        size_bytes=source.stat().st_size,
        media_type="text/markdown",
        storage_key=PurePosixPath("bb/digest"),
        original_name=source.name,
    )

    _exercise(PlainTextParser(), artifact, source)
