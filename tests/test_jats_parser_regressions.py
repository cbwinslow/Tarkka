from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
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
