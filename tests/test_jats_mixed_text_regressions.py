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
