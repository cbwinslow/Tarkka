from __future__ import annotations

import pytest

from tarkka.infrastructure.bibliography_interchange import parse_bibtex, parse_ris

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_bibtex_accepts_trailing_field_comma() -> None:
    record = parse_bibtex("@article{key, title={Study},}")[0]

    assert record.title == "Study"


def test_ris_ignores_blank_lines_around_records() -> None:
    records = parse_ris("\nTY  - JOUR\nTI  - Study\nER  -\n\n")

    assert len(records) == 1
    assert records[0].title == "Study"
