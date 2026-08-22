from __future__ import annotations

import json

import pytest

from tarkka.domain.bibliography import BibliographyFormat
from tarkka.infrastructure.bibliography_interchange import (
    BibliographyParseError,
    parse_bibliography_bytes,
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


def test_bibtex_expands_macros_in_title_and_author() -> None:
    text = r'''
@string{paperTitle = "Macro Study"}
@string{paperAuthor = "Smith, Jane and Doe, John"}
@article{macro,
  title = paperTitle,
  author = paperAuthor,
  year = 2024
}
'''

    record = parse_bibtex(text)[0]

    assert record.title == "Macro Study"
    assert record.authors == ("Smith, Jane", "Doe, John")


def test_bibtex_ignores_percent_comments_without_dropping_literal_percent() -> None:
    text = r'''
% @article{fake, title={Must not appear}}
@article{real,
  title = {Observed 50\% response}, % inline comment with @article{fake2,
  year = 2024,
  url = "https://example.test/a%20b"
}
'''

    records = parse_bibtex(text)

    assert len(records) == 1
    assert records[0].source_key == "real"
    assert records[0].title == r"Observed 50\% response"
    assert records[0].url == "https://example.test/a%20b"


def test_parenthesized_bibtex_ignores_closing_paren_inside_braced_value() -> None:
    record = parse_bibtex(
        "@article(paren, title={Analysis (with nested ) punctuation)}, year={2024})"
    )[0]

    assert record.source_key == "paren"
    assert record.title == "Analysis (with nested ) punctuation)"
    assert record.year == 2024


def test_bibtex_doi_url_ignores_query_fragment_and_citation_punctuation() -> None:
    record = parse_bibtex(
        "@article{doi-url, title={Study}, "
        "url={https://doi.org/10.1000/example.?download=1#page}}"
    )[0]

    assert record.doi == "10.1000/example"


def test_bibtex_conflicting_explicit_and_url_dois_fail_closed() -> None:
    with pytest.raises(BibliographyParseError, match="conflicting DOI"):
        parse_bibtex(
            "@article{conflict, title={Study}, doi={10.1000/a}, "
            "url={https://doi.org/10.1000/b}}"
        )


def test_bibtex_extension_is_supported() -> None:
    records = parse_bibliography_bytes(
        "refs.bibtex",
        b"@article{one, title={BibTeX Extension}}",
    )

    assert records[0].title == "BibTeX Extension"


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
    assert record.fields["TI"] == ("Evidence across\n      multiple lines",)


def test_ris_accepts_common_spacing_variations() -> None:
    record = parse_ris("TY - JOUR\nTI\t- Spacing Study\nER -\n")[0]

    assert record.title == "Spacing Study"


def test_ris_derives_doi_from_url_and_rejects_conflicts() -> None:
    record = parse_ris(
        "TY  - JOUR\nTI  - DOI Study\nUR  - https://doi.org/10.1000/ris-url.\nER  -\n"
    )[0]
    assert record.doi == "10.1000/ris-url"

    with pytest.raises(BibliographyParseError, match="conflicting DOI"):
        parse_ris(
            "TY  - JOUR\nTI  - Conflict\nDO  - 10.1000/a\n"
            "UR  - https://doi.org/10.1000/b\nER  -\n"
        )


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
    assert record.doi == "10.1000/csl"
    assert record.fields["custom"] == {"preserved": True}


def test_csl_json_items_wrapper_is_supported() -> None:
    record = parse_csl_json(
        json.dumps({"items": [{"id": "one", "type": "book", "title": "Wrapped"}]})
    )[0]

    assert record.source_key == "one"
    assert record.entry_type == "book"


def test_csl_json_preserves_numeric_ids_but_not_boolean_ids() -> None:
    numeric = parse_csl_json(
        json.dumps({"id": 42, "type": "book", "title": "Numeric ID"})
    )[0]
    boolean = parse_csl_json(
        json.dumps({"id": True, "type": "book", "title": "Boolean ID"})
    )[0]

    assert numeric.source_key == "42"
    assert boolean.source_key.startswith("csl-json:0:")


def test_csl_json_derives_doi_from_url_and_rejects_conflicts() -> None:
    record = parse_csl_json(
        json.dumps(
            {
                "id": "url-doi",
                "type": "article-journal",
                "title": "CSL DOI URL",
                "URL": "https://doi.org/10.1000/csl-url#fragment",
            }
        )
    )[0]
    assert record.doi == "10.1000/csl-url"

    with pytest.raises(BibliographyParseError, match="conflicting DOI"):
        parse_csl_json(
            json.dumps(
                {
                    "id": "conflict",
                    "type": "article-journal",
                    "title": "Conflict",
                    "DOI": "10.1000/a",
                    "URL": "https://doi.org/10.1000/b",
                }
            )
        )


def test_csl_json_requires_item_type() -> None:
    with pytest.raises(BibliographyParseError, match="type must not be blank"):
        parse_csl_json(json.dumps({"id": "one", "title": "Missing Type"}))


def test_csl_json_invalid_integer_year_is_treated_as_absent() -> None:
    raw = {
        "id": "one",
        "type": "article-journal",
        "title": "Study",
        "issued": {"date-parts": [[-1]]},
    }
    record = parse_csl_json(json.dumps(raw))[0]

    assert record.year is None


def test_parse_bibliography_bytes_rejects_non_utf8_input() -> None:
    with pytest.raises(BibliographyParseError, match="not UTF-8"):
        parse_bibliography_bytes("refs.bib", b"\xff\xfe\x00")


def test_bibtex_rejects_unterminated_entry() -> None:
    with pytest.raises(BibliographyParseError, match="unterminated"):
        parse_bibtex("@article{broken, title={Missing close}")


def test_ris_rejects_unterminated_record() -> None:
    with pytest.raises(BibliographyParseError, match="missing ER"):
        parse_ris("TY  - JOUR\nTI  - Broken\n")
