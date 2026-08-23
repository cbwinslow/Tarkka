from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.jats_parser import JatsParser

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000088")


def _artifact(path: Path) -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="9" * 64,
        size_bytes=path.stat().st_size,
        media_type="application/jats+xml",
        storage_key=PurePosixPath("99/jats-mixed-text"),
        original_name=path.name,
    )


def test_jats_preserves_direct_mixed_section_text_without_structural_duplication(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mixed-text.nxml"
    # Synthetic fixture authored for Tarkka tests; no external source/license restrictions.
    path.write_text(
        """<article><body>
  <sec id="parent"><title>Methods</title>
    Leading <italic>mixed</italic> text.
    <p>Explicit paragraph.</p>
    Between blocks.
    <disp-formula id="eq1"><tex-math>x = 1</tex-math></disp-formula>
    After equation.
    <sec id="child"><title>Nested</title><p>Child paragraph.</p></sec>
    Trailing parent text.
  </sec>
</body></article>""",
        encoding="utf-8",
    )

    document = JatsParser().parse(_artifact(path), path)

    parent, child = document.sections
    assert parent.title == "Methods"
    assert [passage.text for passage in parent.passages] == [
        "Leading mixed text.",
        "Explicit paragraph.",
        "Between blocks.",
        "After equation.",
        "Trailing parent text.",
    ]
    assert [passage.text for passage in child.passages] == ["Child paragraph."]
    assert all("x = 1" not in passage.text for passage in parent.passages)
    assert all("Nested" not in passage.text for passage in parent.passages)


def test_jats_preserves_inline_adjacency_and_explicit_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "inline-adjacency.nxml"
    path.write_text(
        """<article><body><sec><title>Results</title>
<p><bold>A</bold><italic>B</italic> <sup>2</sup></p>
</sec></body></article>""",
        encoding="utf-8",
    )

    document = JatsParser().parse(_artifact(path), path)

    assert [passage.text for passage in document.sections[0].passages] == ["AB 2"]


def test_jats_excludes_grouped_and_nested_structural_artifacts_from_passages(
    tmp_path: Path,
) -> None:
    path = tmp_path / "structural-groups.nxml"
    path.write_text(
        """<article><body><sec><title>Results</title>
Before.
<fig-group>
  <fig><caption><p>Figure caption leak.</p></caption></fig>
</fig-group>
After figure.
<table-wrap-group>
  <table-wrap>
    <caption><p>Table caption leak.</p></caption>
    <table><tr><td>Cell leak.</td></tr></table>
  </table-wrap>
</table-wrap-group>
After table.
<disp-formula-group>
  <disp-formula><tex-math>x + y</tex-math></disp-formula>
</disp-formula-group>
After formula.
<p>
  Paragraph before
  <fig><caption><p>Nested figure leak.</p></caption></fig>
  after
  <table-wrap>
    <table><tr><td>Nested cell leak.</td></tr></table>
  </table-wrap>
  end.
</p>
<list>
  <list-item>
    <p>List item.</p>
    <fig><caption><p>List caption leak.</p></caption></fig>
  </list-item>
</list>
<def-list>
  <def-item><term>Term</term> <def><p>Definition.</p></def></def-item>
</def-list>
</sec></body></article>""",
        encoding="utf-8",
    )

    document = JatsParser().parse(_artifact(path), path)
    passages = [passage.text for passage in document.sections[0].passages]

    assert passages == [
        "Before.",
        "After figure.",
        "After table.",
        "After formula.",
        "Paragraph before after end.",
        "List item.",
        "Term Definition.",
    ]
    leaked = " ".join(passages)
    for forbidden in (
        "Figure caption leak",
        "Table caption leak",
        "Cell leak",
        "x + y",
        "Nested figure leak",
        "Nested cell leak",
        "List caption leak",
    ):
        assert forbidden not in leaked


def test_jats_mixed_text_ignores_whitespace_only_direct_nodes(tmp_path: Path) -> None:
    path = tmp_path / "whitespace.nxml"
    path.write_text(
        """<article><body><sec><title>Methods</title>
  <p>Only paragraph.</p>
</sec></body></article>""",
        encoding="utf-8",
    )

    document = JatsParser().parse(_artifact(path), path)

    assert [passage.text for passage in document.sections[0].passages] == [
        "Only paragraph."
    ]
