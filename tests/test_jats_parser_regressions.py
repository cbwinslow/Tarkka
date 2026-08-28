from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage import jats_parser
from tarkka.infrastructure.storage.jats_parser import JatsParser

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _artifact(path: Path) -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="f" * 64,
        size_bytes=path.stat().st_size,
        media_type="application/jats+xml",
        storage_key=PurePosixPath("ff/jats-regression"),
        original_name=path.name,
    )


def _parse(tmp_path: Path, xml: str):
    path = tmp_path / "fixture.nxml"
    path.write_text(xml, encoding="utf-8")
    return JatsParser().parse_native(_artifact(path), path)


def test_jats_preserves_native_abstract_title(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """<article>
  <front><article-meta>
    <title-group><article-title>Article</article-title></title-group>
    <abstract><title>Background and objectives</title><p>Abstract body.</p></abstract>
  </article-meta></front>
</article>""",
    )

    assert [section.title for section in result.document.sections] == [
        "Background and objectives"
    ]
    assert result.document.sections[0].passages[0].text == "Abstract body."


def test_jats_finds_mathml_nested_inside_alternatives(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """<article><body><sec><title>Results</title>
  <disp-formula id="eq1"><label>(1)</label><alternatives>
    <mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML">
      <mml:mi>y</mml:mi><mml:mo>=</mml:mo><mml:mi>x</mml:mi>
    </mml:math>
  </alternatives></disp-formula>
</sec></body></article>""",
    )

    assert len(result.document.equations) == 1
    assert result.document.equations[0].source_text == "y=x"


def test_jats_table_column_count_accounts_for_colspan(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """<article><body><sec><title>Results</title>
  <table-wrap id="t1"><table>
    <tr><th colspan="3">Grouped heading</th></tr>
    <tr><td>A</td><td>B</td><td>C</td></tr>
  </table></table-wrap>
</sec></body></article>""",
    )

    assert len(result.document.tables) == 1
    assert result.document.tables[0].row_count == 2
    assert result.document.tables[0].column_count == 3


@pytest.mark.parametrize("colspan", ["0", "-1", "not-a-number"])
def test_jats_rejects_invalid_table_colspan(tmp_path: Path, colspan: str) -> None:
    path = tmp_path / "bad-colspan.nxml"
    path.write_text(
        f"""<article><body><sec><title>Results</title>
  <table-wrap><table><tr><td colspan="{colspan}">A</td></tr></table></table-wrap>
</sec></body></article>""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid JATS table colspan"):
        JatsParser().parse_native(_artifact(path), path)


def test_jats_rejects_duplicate_bibliography_native_ids(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-refs.nxml"
    path.write_text(
        """<article><back><ref-list>
  <ref id="R1"><mixed-citation>First reference</mixed-citation></ref>
  <ref id="R1"><mixed-citation>Second reference</mixed-citation></ref>
</ref-list></back></article>""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JATS bibliography native ID: R1"):
        JatsParser().parse_native(_artifact(path), path)


def test_jats_support_detection_and_parse_error_taxonomy(tmp_path: Path) -> None:
    parser = JatsParser()
    generic = Artifact(
        artifact_id=uuid4(),
        sha256="a" * 64,
        size_bytes=1,
        media_type="application/octet-stream",
        storage_key=PurePosixPath("aa/jats-support"),
        original_name=None,
    )
    by_extension = Artifact(
        artifact_id=uuid4(),
        sha256="b" * 64,
        size_bytes=1,
        media_type="application/octet-stream",
        storage_key=PurePosixPath("bb/jats-support"),
        original_name="paper.nxml",
    )

    assert parser.supports(generic) is False
    assert parser.supports(by_extension) is True

    valid = tmp_path / "valid.nxml"
    valid.write_text("<article><body><p>Body text.</p></body></article>", encoding="utf-8")
    assert parser.parse(_artifact(valid), valid).sections[0].passages[0].text == "Body text."

    malformed = tmp_path / "malformed.nxml"
    malformed.write_text("<article>", encoding="utf-8")
    with pytest.raises(ValueError, match="unable to parse JATS XML") as exc_info:
        parser.parse_native(_artifact(malformed), malformed)
    assert isinstance(exc_info.value.__cause__, ET.ParseError)

    wrong_root = tmp_path / "wrong-root.nxml"
    wrong_root.write_text("<book/>", encoding="utf-8")
    with pytest.raises(ValueError, match="requires an <article> root"):
        parser.parse_native(_artifact(wrong_root), wrong_root)


def test_jats_sectionless_body_preserves_lists_and_mixed_content(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """<article><body>
Lead <italic>inline</italic> tail.
<p>Paragraph.</p>
<list/>
<def-list/>
<list><list-item>First item.</list-item></list>
<def-list><def-item><term>Term</term><def>Definition.</def></def-item></def-list>
<fig><caption><p>Artifact-only caption.</p></caption></fig>
Trailing text.
</body></article>""",
    )

    assert len(result.document.sections) == 1
    passages = [item.text for item in result.document.sections[0].passages]
    assert "Lead inline tail." in passages
    assert "Paragraph." in passages
    assert "First item." in passages
    assert any("Term" in item and "Definition." in item for item in passages)
    assert all("Artifact-only caption" not in item for item in passages)


def test_jats_fallbacks_for_sparse_equations_references_and_links(tmp_path: Path) -> None:
    result = _parse(
        tmp_path,
        """<article>
<front><article-meta>
  <article-id>untyped-id</article-id>
  <article-id pub-id-type="doi"></article-id>
</article-meta></front>
<body><sec>
  <disp-formula id="eq-sparse"><label>Equation label</label></disp-formula>
  <p><xref ref-type="bibr"></xref> <xref ref-type="bibr">[?]</xref></p>
  <supplementary-material>Missing href</supplementary-material>
</sec></body>
<back><ref-list>
  <ref><pub-id>untyped</pub-id><pub-id pub-id-type="doi"></pub-id></ref>
</ref-list></back>
</article>""",
    )

    assert result.document.equations[0].source_text == "Equation label"
    assert result.references[0].raw_text == "untyped"
    assert dict(result.references[0].identifiers) == {}
    assert len(result.mentions) == 1
    assert result.mentions[0].raw_text == "[?]"
    assert result.mentions[0].reference_id is None
    assert result.mentions[0].source_anchor is None
    assert result.resource_links == ()
    assert result.observation.provider_record_id is None
    assert result.observation.metadata["article_ids"] == {}


def test_jats_namespace_helpers_tolerate_comments_and_missing_nodes() -> None:
    root = ET.Element("{urn:test}article")
    comment = ET.Comment("comment")
    root.append(comment)

    jats_parser._strip_element_namespaces(root)

    assert root.tag == "article"
    assert comment.tag is ET.Comment
    assert jats_parser._text(None) == ""
