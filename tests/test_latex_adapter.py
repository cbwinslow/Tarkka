from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

from tarkka.domain.models import Artifact
from tarkka.domain.source_observations import Capability, ObservationBasis, ResourceRelation
from tarkka.infrastructure.storage.latex_parser import LatexParser

FIXTURE = Path("tests/fixtures/latex/structured_article.tex")


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="a" * 64,
        size_bytes=FIXTURE.stat().st_size,
        media_type="text/x-tex",
        storage_key=PurePosixPath("aa/latex-fixture"),
        original_name="article.tex",
    )


def test_latex_adapter_preserves_native_structure_and_source_artifacts() -> None:
    result = LatexParser().parse_native(_artifact(), FIXTURE)
    document = result.document

    assert document.title == "Native LaTeX Fixture"
    assert document.parser_name == "latex"
    assert [section.title for section in document.sections] == ["Introduction", "Method"]
    assert document.sections[0].passages[0].text == "Prior work [smith2024] motivates this model."
    assert document.figures[0].label == "fig:model"
    assert document.figures[0].caption == "Observed and fitted values."
    assert document.tables[0].label == "tab:coefficients"
    assert document.tables[0].row_count == 2
    assert document.tables[0].column_count == 2
    assert document.equations[0].label == "eq:model"
    assert document.equations[0].source_text == "y = a + bx"


def test_latex_adapter_preserves_citations_and_graphic_links() -> None:
    result = LatexParser().parse_native(_artifact(), FIXTURE)

    assert result.references[0].source_anchor == "smith2024"
    assert result.references[0].raw_text == "Smith, A. (2024). Evidence-grounded modeling."
    assert result.mentions[0].raw_text == "[smith2024]"
    assert result.mentions[0].reference_id == result.references[0].reference_id
    assert result.mentions[0].passage_id is not None
    assert result.observation.basis is ObservationBasis.NATIVE
    assert result.observation.metadata["document_class"] == "article"
    assert result.observation.metadata["native_labels"] == (
        "eq:model",
        "fig:model",
        "tab:coefficients",
    )
    assert result.resource_links[0].target_uri == "figures/model.png"
    assert result.resource_links[0].relation is ResourceRelation.RELATED
    assert result.resource_links[0].media_type == "image/png"


def test_latex_adapter_ids_are_stable_and_capabilities_are_explicit() -> None:
    parser = LatexParser()
    artifact = _artifact()

    first = parser.parse_native(artifact, FIXTURE)
    second = parser.parse_native(artifact, FIXTURE)

    assert first.document.document_id == second.document.document_id
    assert first.document.figures[0].figure_id == second.document.figures[0].figure_id
    assert first.references[0].reference_id == second.references[0].reference_id
    assert parser.manifest.supports(
        Capability.DOCUMENT_STRUCTURE,
        Capability.BIBLIOGRAPHY,
        Capability.INLINE_CITATIONS,
        Capability.FIGURES,
        Capability.TABLES,
        Capability.EQUATIONS,
        Capability.LINK_DISCOVERY,
    )
