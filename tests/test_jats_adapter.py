from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import Capability, ObservationBasis, ResourceRelation
from tarkka.infrastructure.storage.jats_parser import JatsParser

FIXTURE = Path("tests/fixtures/jats/sample_article.xml")


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="b" * 64,
        size_bytes=FIXTURE.stat().st_size,
        media_type="application/jats+xml",
        storage_key=PurePosixPath("bb/jats-fixture"),
        original_name="sample_article.nxml",
    )


def test_jats_adapter_preserves_native_structure_without_markdown_flattening() -> None:
    parser = JatsParser()
    artifact = _artifact()

    result = parser.parse_native(artifact, FIXTURE)
    document = result.document

    assert parser.supports(artifact)
    assert document.title == "Native Structure Fixture"
    assert document.parser_name == "jats"
    assert [section.title for section in document.sections] == [
        "Abstract",
        "Methods",
        "Model",
        "Results",
    ]
    methods, model = document.sections[1:3]
    assert model.parent_section_id == methods.section_id
    assert methods.level == 1
    assert model.level == 2
    assert [passage.text for passage in methods.passages] == [
        "First methods paragraph.",
        "Preserved list item.",
    ]

    assert len(document.figures) == 1
    assert document.figures[0].label == "Figure 1"
    assert document.figures[0].caption == "Preserved figure caption."
    assert document.figures[0].figure_type == "diagram"

    assert len(document.tables) == 1
    assert document.tables[0].label == "Table 1"
    assert document.tables[0].caption == "Preserved table caption."
    assert document.tables[0].row_count == 3
    assert document.tables[0].column_count == 2

    assert len(document.equations) == 1
    assert document.equations[0].label == "(1)"
    assert document.equations[0].source_text == "y = a + bx"


def test_jats_adapter_preserves_bibliography_citations_and_supplements() -> None:
    result = JatsParser().parse_native(_artifact(), FIXTURE)

    assert [reference.source_anchor for reference in result.references] == ["R1", "R2"]
    assert dict(result.references[0].identifiers) == {"doi": "10.1000/first"}
    assert dict(result.references[1].identifiers) == {"pmid": "987654"}
    assert len(result.mentions) == 3
    assert all(mention.reference_id is not None for mention in result.mentions)
    assert {mention.source_anchor for mention in result.mentions} == {"R1", "R2"}

    assert len(result.resource_links) == 1
    link = result.resource_links[0]
    assert link.target_uri == "supplement/data.csv"
    assert link.relation is ResourceRelation.SUPPLEMENT
    assert link.media_type == "text/csv"

    assert result.observation.basis is ObservationBasis.NATIVE
    assert result.observation.provider_record_id == "pmcid:PMC123456"
    assert result.observation.metadata["article_ids"] == {
        "pmcid": "PMC123456",
        "doi": "10.1000/tarkka.fixture",
    }
    assert result.observation.metadata["counts"]["references"] == 2


def test_jats_ids_are_stable_for_same_source_artifact() -> None:
    parser = JatsParser()
    artifact = _artifact()

    first = parser.parse_native(artifact, FIXTURE)
    second = parser.parse_native(artifact, FIXTURE)

    assert first.document.document_id == second.document.document_id
    assert [item.section_id for item in first.document.sections] == [
        item.section_id for item in second.document.sections
    ]
    assert [item.reference_id for item in first.references] == [
        item.reference_id for item in second.references
    ]
    assert [item.mention_id for item in first.mentions] == [
        item.mention_id for item in second.mentions
    ]


def test_jats_default_namespace_preserves_descendants(tmp_path: Path) -> None:
    path = tmp_path / "namespaced.nxml"
    path.write_text(
        """<article xmlns="urn:jats:test">
  <front><article-meta><title-group><article-title>Namespaced</article-title></title-group></article-meta></front>
  <body><sec id="s1"><title>Methods</title><p>Native paragraph.</p></sec></body>
</article>""",
        encoding="utf-8",
    )
    artifact = Artifact(
        artifact_id=uuid4(),
        sha256="d" * 64,
        size_bytes=path.stat().st_size,
        media_type="application/jats+xml",
        storage_key=PurePosixPath("dd/namespaced"),
        original_name="namespaced.nxml",
    )

    document = JatsParser().parse(artifact, path)

    assert document.title == "Namespaced"
    assert [section.title for section in document.sections] == ["Methods"]
    assert document.sections[0].passages[0].text == "Native paragraph."


def test_jats_capabilities_are_explicit() -> None:
    manifest = JatsParser.manifest

    assert manifest.supports(
        Capability.DOCUMENT_STRUCTURE,
        Capability.BIBLIOGRAPHY,
        Capability.INLINE_CITATIONS,
        Capability.FIGURES,
        Capability.TABLES,
        Capability.EQUATIONS,
        Capability.SUPPLEMENTS,
    )


def test_jats_parser_rejects_non_article_xml(tmp_path: Path) -> None:
    path = tmp_path / "not-jats.xml"
    path.write_text("<root><p>not JATS</p></root>", encoding="utf-8")
    artifact = Artifact(
        artifact_id=uuid4(),
        sha256="c" * 64,
        size_bytes=path.stat().st_size,
        media_type="application/xml",
        storage_key=PurePosixPath("cc/not-jats"),
        original_name="not-jats.xml",
    )

    with pytest.raises(ValueError, match="<article> root"):
        JatsParser().parse(artifact, path)
