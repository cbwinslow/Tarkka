from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import Capability, ObservationBasis, ResourceRelation
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
