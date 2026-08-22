from __future__ import annotations

import json

import pytest

from tarkka.domain.bibliography import BibliographyFormat
from tarkka.infrastructure.bibliography_interchange import (
    BibliographyParseError,
    parse_bibtex,
    parse_csl_json,
    parse_ris,
)


def test_bibtex_preserves_native_fields_macros_and_identifiers() -> None:
    text = r'''
@string{journal = "Journal of {Research}"}
@article{smith2024,
  title = {A {Structured} Study},
  author = {Smith, Jane and Doe, John},
  year = 2024,
  journal = journal,
  url = "https://doi.org/10.1000/example",
  note = {native {field} value}
}
'''

    records = parse_bibtex(text)

    assert len(records) == 1
    record = records[0]
    assert record.source_format is BibliographyFormat.BIBTEX
    assert record.source_key == "smith2024"
    assert record.title == "A {Structured} Study"
    assert record.authors == ("Smith, Jane", "Doe, John")
    assert record.year == 2024
    assert record.doi == "10.1000/example"
    assert record.fields["journal"] == "Journal of {Research}"
    assert record.fields["note"] == "native {field} value"


def test_ris_preserves_repeated_fields_and_continuations() -> None:
    text = """TY  - JOUR
ID  - local-1
TI  - Evidence across
      multiple lines
AU  - Smith, Jane
AU  - Doe, John
PY  - 2023/05/01
DO  - 10.1000/ris
ER  -
"""

    record = parse_ris(text)[0]

    assert record.source_format is BibliographyFormat.RIS
    assert record.title == "Evidence across multiple lines"
    assert record.authors == ("Smith, Jane", "Doe, John")
    assert record.year == 2023
    assert record.doi == "10.1000/ris"
    assert record.fields["AU"] == ("Smith, Jane", "Doe, John")


def test_csl_json_preserves_native_object_and_names() -> None:
    raw = {
        "id": "csl-1",
        "type": "article-journal",
        "title": "CSL Study",
        "author": [
            {"family": "Smith", "given": "Jane"},
            {"literal": "Example Consortium"},
        ],
        "issued": {"date-parts": [[2022, 4, 1]]},
        "DOI": "https://doi.org/10.1000/csl",
        "URL": "https://example.test/paper",
        "custom": {"preserved": True},
    }

    record = parse_csl_json(json.dumps([raw]))[0]

    assert record.source_format is BibliographyFormat.CSL_JSON
    assert record.authors == ("Smith, Jane", "Example Consortium")
    assert record.year == 2022
    assert record.doi == "https://doi.org/10.1000/csl"
    assert record.fields["custom"] == {"preserved": True}


def test_bibtex_rejects_unterminated_entry() -> None:
    with pytest.raises(BibliographyParseError, match="unterminated"):
        parse_bibtex("@article{broken, title={Missing close}")


def test_ris_rejects_unterminated_record() -> None:
    with pytest.raises(BibliographyParseError, match="missing ER"):
        parse_ris("TY  - JOUR\nTI  - Broken\n")
