from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import Capability, ObservationBasis, ResourceRelation
from tarkka.infrastructure.storage import semantic_html_parser
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser

FIXTURE = Path("tests/fixtures/html/semantic_article.html")


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="f" * 64,
        size_bytes=FIXTURE.stat().st_size,
        media_type="text/html",
        storage_key=PurePosixPath("ff/semantic-html"),
        original_name="article.html",
    )


def _generic_artifact(*, original_name: str | None = None) -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="e" * 64,
        size_bytes=1,
        media_type="application/octet-stream",
        storage_key=PurePosixPath("ee/semantic-html-edge"),
        original_name=original_name,
    )


def test_semantic_html_preserves_structure_and_first_class_artifacts() -> None:
    parser = SemanticHtmlParser()
    artifact = _artifact()

    result = parser.parse_native(artifact, FIXTURE)
    document = result.document

    assert parser.supports(artifact)
    assert document.title == "Semantic HTML Fixture"
    assert [section.title for section in document.sections] == [
        "Introduction",
        "Methods",
        "References",
    ]
    assert document.sections[1].parent_section_id == document.sections[0].section_id
    assert document.sections[0].passages[0].text == "Prior work [1] motivates this study."

    assert len(document.figures) == 1
    assert document.figures[0].label == "Figure 1"
    assert document.figures[0].caption == "Observed and fitted values."

    assert len(document.tables) == 1
    assert document.tables[0].label == "Table 1"
    assert document.tables[0].caption == "Model coefficients."
    assert document.tables[0].row_count == 2
    assert document.tables[0].column_count == 2

    assert len(document.equations) == 1
    assert document.equations[0].label == "Equation 1"
    assert document.equations[0].source_text == "y=x"


def test_semantic_html_preserves_citations_metadata_and_resource_links() -> None:
    result = SemanticHtmlParser().parse_native(_artifact(), FIXTURE)

    assert len(result.references) == 1
    assert result.references[0].source_anchor == "ref-1"
    assert dict(result.references[0].identifiers) == {"doi": "10.1000/example"}
    assert len(result.mentions) == 1
    assert result.mentions[0].raw_text == "[1]"
    assert result.mentions[0].reference_id == result.references[0].reference_id

    assert result.observation.basis is ObservationBasis.NATIVE
    assert result.observation.provider_record_id == "10.1000/html.fixture"
    assert result.observation.metadata["language"] == "en"
    assert result.observation.metadata["citation_title"] == "Semantic HTML Fixture"

    relations = {link.relation for link in result.resource_links}
    assert ResourceRelation.CANONICAL in relations
    assert ResourceRelation.SUPPLEMENT in relations
    supplement = next(
        link for link in result.resource_links if link.relation is ResourceRelation.SUPPLEMENT
    )
    assert supplement.target_uri == "supplement.csv"
    assert supplement.media_type == "text/csv"


def test_semantic_html_ids_are_stable_for_same_artifact() -> None:
    parser = SemanticHtmlParser()
    artifact = _artifact()

    first = parser.parse_native(artifact, FIXTURE)
    second = parser.parse_native(artifact, FIXTURE)

    assert first.document.document_id == second.document.document_id
    assert [section.section_id for section in first.document.sections] == [
        section.section_id for section in second.document.sections
    ]
    assert first.references[0].reference_id == second.references[0].reference_id
    assert first.mentions[0].mention_id == second.mentions[0].mention_id


def test_semantic_html_capabilities_are_explicit() -> None:
    manifest = SemanticHtmlParser.manifest

    assert manifest.supports(
        Capability.DOCUMENT_STRUCTURE,
        Capability.BIBLIOGRAPHY,
        Capability.INLINE_CITATIONS,
        Capability.FIGURES,
        Capability.TABLES,
        Capability.EQUATIONS,
        Capability.SUPPLEMENTS,
        Capability.LINK_DISCOVERY,
    )


def test_semantic_html_support_and_error_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = SemanticHtmlParser()
    assert parser.supports(_generic_artifact()) is False
    assert parser.supports(_generic_artifact(original_name="paper.xhtml")) is True

    path = tmp_path / "minimal.html"
    path.write_text("<html><body><p>Body.</p></body></html>", encoding="utf-8")
    artifact = _generic_artifact(original_name="minimal.html")
    assert parser.parse(artifact, path).sections[0].passages[0].text == "Body."

    missing = tmp_path / "missing.html"
    with pytest.raises(ValueError, match="unable to read semantic HTML") as exc_info:
        parser.parse_native(artifact, missing)
    assert isinstance(exc_info.value.__cause__, OSError)

    class BrokenTreeBuilder:
        def __init__(self) -> None:
            self.root = semantic_html_parser._Node("document", {})

        def feed(self, _source: str) -> None:
            raise ValueError("synthetic parser failure")

        def close(self) -> None:
            raise AssertionError("close should not run after feed failure")

    monkeypatch.setattr(semantic_html_parser, "_TreeBuilder", BrokenTreeBuilder)
    with pytest.raises(ValueError, match="unable to parse semantic HTML") as parse_exc:
        parser.parse_native(artifact, path)
    assert isinstance(parse_exc.value.__cause__, ValueError)


def test_semantic_html_tree_builder_recovers_from_self_closing_and_mismatched_tags() -> None:
    builder = semantic_html_parser._TreeBuilder()

    builder.handle_startendtag("section", [("ID", None)])
    assert builder.root.children[0].attrs == {"id": ""}
    assert builder._stack == [builder.root]

    builder.handle_starttag("section", [])
    builder.handle_starttag("span", [])
    builder.handle_endtag("section")
    assert builder._stack == [builder.root]

    builder.handle_endtag("missing")
    builder.handle_data("tail")
    assert builder.root.content[-1] == "tail"


def test_semantic_html_sparse_structure_and_heading_parentage(tmp_path: Path) -> None:
    path = tmp_path / "sparse.html"
    path.write_text(
        """<html xml:lang="fr"><head><title></title></head><body>
<script>ignored script text</script>
<p>Leading paragraph.</p>
<h7>Not a supported heading level</h7>
<h2 id="outer">Outer</h2><p>Outer body.</p>
<h4 id="inner">Inner</h4><blockquote><span>Nested quote.</span></blockquote>
<h2 id="sibling">Sibling</h2>
<figure id="fig-empty"><figcaption></figcaption></figure>
<table id="table-empty"></table>
<math id="eq-empty"></math>
<div role="doc-biblioentry" id="blank-ref"></div>
<a role="doc-biblioref" href="#blank-ref"></a>
<a href="#fragment">fragment</a>
<a href="https://example.test/unclassified">ordinary</a>
</body></html>""",
        encoding="utf-8",
    )

    result = SemanticHtmlParser().parse_native(
        _generic_artifact(original_name="sparse.html"), path
    )
    document = result.document

    assert [section.title for section in document.sections] == [
        "sparse.html",
        "Outer",
        "Inner",
        "Sibling",
    ]
    assert document.sections[2].parent_section_id == document.sections[1].section_id
    assert document.sections[3].parent_section_id is None
    assert all("ignored script text" not in p.text for s in document.sections for p in s.passages)
    assert document.figures[0].label is None
    assert document.figures[0].caption is None
    assert document.tables[0].row_count == 0
    assert document.tables[0].column_count == 0
    assert document.equations[0].source_text is None
    assert result.references == ()
    assert result.mentions == ()
    assert result.resource_links == ()
    assert result.observation.metadata["language"] == "fr"


def test_semantic_html_classifies_all_supported_resource_relations(tmp_path: Path) -> None:
    path = tmp_path / "links.html"
    path.write_text(
        """<html><body>
<a rel="alternate" href="alternate.html">Alternate</a>
<a rel="dataset" href="data.csv">Dataset</a>
<a rel="software" href="code.zip">Code</a>
<a download href="download.bin">Download</a>
<a role="doc-supplementary" href="supplement.txt">Supplement</a>
<link rel="canonical" href="https://example.test/article" />
</body></html>""",
        encoding="utf-8",
    )

    result = SemanticHtmlParser().parse_native(
        _generic_artifact(original_name="links.html"), path
    )

    assert {link.relation for link in result.resource_links} == {
        ResourceRelation.ALTERNATE,
        ResourceRelation.DATASET,
        ResourceRelation.SOFTWARE,
        ResourceRelation.SUPPLEMENT,
        ResourceRelation.CANONICAL,
    }


def test_semantic_html_metadata_doi_and_tree_helpers_cover_empty_values() -> None:
    builder = semantic_html_parser._TreeBuilder()
    builder.feed(
        """<meta name="" content="ignored">
<meta name="citation_title" content="">
<meta property="citation_title" content="First">
<meta name="citation_title" content="Second">"""
    )
    builder.close()

    assert semantic_html_parser._metadata(builder.root) == {"citation_title": "First"}
    assert semantic_html_parser._document_language(builder.root) is None
    assert semantic_html_parser._doi_from_uri("https://example.test/no-doi") is None
    assert semantic_html_parser._doi_from_uri("https://doi.org/") is None
    assert semantic_html_parser._first_text(builder.root, "missing") == ""
    assert semantic_html_parser._text(semantic_html_parser._Node("script", {})) == ""

    root = semantic_html_parser._Node("document", {})
    paragraph = semantic_html_parser._Node("p", {})
    target = semantic_html_parser._Node("span", {})
    paragraph.children.append(target)
    root.children.append(paragraph)
    assert semantic_html_parser._has_ancestor_block(root, target) is True
    assert semantic_html_parser._has_ancestor_block(root, semantic_html_parser._Node("x", {})) is False
