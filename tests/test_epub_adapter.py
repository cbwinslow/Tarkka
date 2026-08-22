from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import Capability, ObservationBasis, ResourceRelation
from tarkka.infrastructure.storage.epub_parser import EpubParser

_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:isbn:9780000000001</dc:identifier>
    <dc:title>EPUB Research Fixture</dc:title>
    <dc:language>en</dc:language>
    <dc:creator>Example Author</dc:creator>
    <meta property="dcterms:modified">2026-08-21T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="chapter-1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter-2" href="text/chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="figure" href="images/plot.png" media-type="image/png"/>
    <item id="styles" href="styles/book.css" media-type="text/css"/>
  </manifest>
  <spine>
    <itemref idref="chapter-1"/>
    <itemref idref="chapter-2"/>
  </spine>
</package>
"""

_CHAPTER_1 = """<!doctype html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
<head><title>Chapter One</title></head>
<body>
<article>
  <h1 id="intro">Introduction</h1>
  <p>First chapter evidence <a epub:type="noteref" href="#note-1">[1]</a>.</p>
  <figure id="fig-1"><img src="../images/plot.png" alt="Figure 1"/><figcaption>Observed values.</figcaption></figure>
  <table id="tab-1"><caption>Coefficients</caption><tr><th>x</th><th>y</th></tr><tr><td>1</td><td>2</td></tr></table>
  <math id="eq-1"><mi>x</mi><mo>=</mo><mn>1</mn></math>
  <aside id="note-1" epub:type="footnote"><p>Chapter note.</p></aside>
</article>
</body>
</html>
"""

_CHAPTER_2 = """<!doctype html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
<head><title>Chapter Two</title></head>
<body>
<article>
  <h1 id="results">Results</h1>
  <p>Second chapter text cites <a role="doc-biblioref" href="#ref-1">[2]</a>.</p>
  <section role="doc-bibliography">
    <h2>References</h2>
    <p id="ref-1" role="doc-biblioentry">Example Study. <a href="https://doi.org/10.1000/epub.example">doi</a></p>
  </section>
  <a rel="supplement" href="../data/supplement.csv" type="text/csv">Supplement</a>
</article>
</body>
</html>
"""


def _write_epub(path: Path, *, package: str = _PACKAGE, container: str = _CONTAINER) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/package.opf", package)
        archive.writestr("OEBPS/text/chapter1.xhtml", _CHAPTER_1)
        archive.writestr("OEBPS/text/chapter2.xhtml", _CHAPTER_2)
        archive.writestr("OEBPS/images/plot.png", b"png")
        archive.writestr("OEBPS/styles/book.css", b"body{}")


def _artifact(path: Path) -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="e" * 64,
        size_bytes=path.stat().st_size,
        media_type="application/epub+zip",
        storage_key=PurePosixPath("ee/fixture.epub"),
        original_name="fixture.epub",
        source_uri=path.as_uri(),
    )


def test_epub_preserves_package_spine_and_semantic_structure(tmp_path: Path) -> None:
    path = tmp_path / "fixture.epub"
    _write_epub(path)
    artifact = _artifact(path)

    result = EpubParser().parse_native(artifact, path)

    assert result.document.title == "EPUB Research Fixture"
    assert [section.title for section in result.document.sections[:3]] == [
        "Introduction",
        "Results",
        "References",
    ]
    assert result.document.sections[0].passages[0].text.startswith("First chapter evidence")
    assert result.document.sections[1].passages[0].text.startswith("Second chapter text")

    assert len(result.document.figures) == 1
    assert result.document.figures[0].caption == "Observed values."
    assert len(result.document.tables) == 1
    assert result.document.tables[0].row_count == 2
    assert result.document.tables[0].column_count == 2
    assert len(result.document.equations) == 1

    assert result.observation.basis is ObservationBasis.NATIVE
    assert result.observation.provider_record_id == "urn:isbn:9780000000001"
    assert result.observation.metadata["package_path"] == "OEBPS/package.opf"
    assert len(result.observation.metadata["parsed_spine"]) == 2


def test_epub_rebases_bibliography_mentions_and_resource_links(tmp_path: Path) -> None:
    path = tmp_path / "fixture.epub"
    _write_epub(path)
    result = EpubParser().parse_native(_artifact(path), path)

    assert len(result.references) == 1
    reference = result.references[0]
    assert dict(reference.identifiers) == {"doi": "10.1000/epub.example"}
    assert reference.source_anchor == "OEBPS/text/chapter2.xhtml::ref-1"

    bibliography_mentions = [mention for mention in result.mentions if mention.raw_text == "[2]"]
    assert len(bibliography_mentions) == 1
    assert bibliography_mentions[0].reference_id == reference.reference_id
    assert bibliography_mentions[0].source_anchor == "OEBPS/text/chapter2.xhtml::ref-1"

    links = {(link.target_uri, link.relation) for link in result.resource_links}
    assert ("OEBPS/text/chapter1.xhtml", ResourceRelation.FULL_TEXT) in links
    assert ("OEBPS/text/chapter2.xhtml", ResourceRelation.FULL_TEXT) in links
    assert ("OEBPS/images/plot.png", ResourceRelation.RELATED) in links
    assert ("OEBPS/data/supplement.csv", ResourceRelation.SUPPLEMENT) in links


def test_epub_ids_and_offsets_are_stable_for_same_artifact(tmp_path: Path) -> None:
    path = tmp_path / "fixture.epub"
    _write_epub(path)
    artifact = _artifact(path)
    parser = EpubParser()

    first = parser.parse_native(artifact, path)
    second = parser.parse_native(artifact, path)

    assert first.document.document_id == second.document.document_id
    assert [section.section_id for section in first.document.sections] == [
        section.section_id for section in second.document.sections
    ]
    assert first.references[0].reference_id == second.references[0].reference_id
    assert first.mentions[-1].mention_id == second.mentions[-1].mention_id

    passages = [passage for section in first.document.sections for passage in section.passages]
    assert passages
    assert all(passage.char_end - passage.char_start == len(passage.text) for passage in passages)
    assert all(
        current.char_start > previous.char_end
        for previous, current in zip(passages, passages[1:], strict=False)
    )


def test_epub_capabilities_are_explicit() -> None:
    manifest = EpubParser.manifest
    assert manifest.supports(
        Capability.DOCUMENT_STRUCTURE,
        Capability.BIBLIOGRAPHY,
        Capability.INLINE_CITATIONS,
        Capability.FIGURES,
        Capability.TABLES,
        Capability.EQUATIONS,
        Capability.LINK_DISCOVERY,
    )


def test_epub_rejects_unsafe_manifest_member(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.epub"
    package = _PACKAGE.replace(
        'href="text/chapter1.xhtml"',
        'href="../../../outside.xhtml"',
    )
    _write_epub(path, package=package)

    with pytest.raises(ValueError, match="unsafe EPUB member path"):
        EpubParser().parse_native(_artifact(path), path)


def test_epub_requires_first_uncompressed_mimetype_entry(tmp_path: Path) -> None:
    path = tmp_path / "bad.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", _CONTAINER)
        archive.writestr("mimetype", "application/epub+zip")

    with pytest.raises(ValueError, match="mimetype entry must be first and uncompressed"):
        EpubParser().parse_native(_artifact(path), path)
