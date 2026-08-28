from __future__ import annotations

import json
from pathlib import Path

import pytest

from tarkka.infrastructure import bibliography_bibtex, bibliography_common, bibliography_csl_json
from tarkka.infrastructure.bibliography_errors import BibliographyParseError
from tarkka.infrastructure.bibliography_interchange import (
    parse_bibliography,
    parse_bibliography_bytes,
    parse_bibtex,
    parse_csl_json,
    parse_ris,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_bibtex_skips_unknown_directives_and_nonrecords() -> None:
    text = r'''
@?ignored
@comment{this, is ignored}
@preamble{"also ignored"}
@article{one,
  title = jan # " Study"
}
'''

    records = parse_bibtex(text)

    assert len(records) == 1
    assert records[0].source_key == "one"
    assert records[0].title == "January Study"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("@article key, title={Study}", "missing an opening delimiter"),
        ("@article{key}", "no field separator"),
        ("@article{, title={Study}}", "blank citation key"),
        ("@article{key, 1bad={Study}}", "invalid BibTeX field"),
        (
            "@article{key, Title={One}, title={Two}}",
            "duplicate BibTeX field",
        ),
        ("@article{key, title {Study}}", "missing '='"),
        ("@article{key, title={Study} junk}", "unexpected trailing content"),
        ("@article{key, title=}", "unexpected end of BibTeX value"),
        ("@article{key, title=#}", "empty BibTeX value atom"),
        ('@article{key, title="unterminated}', "unterminated quoted BibTeX value"),
    ],
)
def test_bibtex_rejects_malformed_entries(text: str, message: str) -> None:
    with pytest.raises(BibliographyParseError, match=message):
        parse_bibtex(text)


def test_bibtex_balances_parenthesized_quoted_values_and_author_gaps() -> None:
    record = parse_bibtex(
        r'@article(key, title="A ) {Nested} \"Quoted\" Study", '
        r'author={Smith and   and Doe}, year=2024)'
    )[0]

    assert record.title == r'A ) {Nested} \"Quoted\" Study'
    assert record.authors == ("Smith", "Doe")
    assert record.year == 2024


def test_bibtex_private_delimiter_and_cleanup_boundaries() -> None:
    assert bibliography_bibtex._is_comment_position(0, 0) is True
    assert bibliography_bibtex._is_comment_position(1, 0) is True
    assert bibliography_bibtex._is_comment_position(0, 1) is True
    assert bibliography_bibtex._is_comment_position(2, 0) is False
    assert bibliography_bibtex._is_comment_position(0, 2) is False

    assert bibliography_bibtex._top_level_delimiter(r"{a\,b}", ",") == -1
    assert bibliography_bibtex._top_level_delimiter('"a,b"', ",") == -1
    assert bibliography_bibtex._top_level_delimiter("(a,b)", ",") == -1

    assert bibliography_bibtex._clean_bibtex_text("{{ Wrapped }}") == "Wrapped"
    assert bibliography_bibtex._clean_bibtex_text("{one}{two}") == "{one}{two}"
    assert bibliography_bibtex._clean_bibtex_text(r"{broken\}") == r"{broken\}"


def test_bibtex_field_lookup_is_case_insensitive_and_missing_safe() -> None:
    fields = {"TiTlE": "Study"}

    assert bibliography_bibtex._field_value(fields, "title") == "Study"
    assert bibliography_bibtex._field_value(fields, "author") is None
    assert bibliography_bibtex._bibtex_authors(None) == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{broken", "invalid CSL-JSON"),
        ("42", "root must be an object or array"),
        ('{"items": {}}', "'items' must be an array"),
        ('["not-an-object"]', "item 0 must be an object"),
        (
            '{"id":"one","type":"book","title":"Study","author":"Ada"}',
            "author must be an array",
        ),
        (
            '{"id":"one","type":"book","title":"Study","author":["Ada"]}',
            "author 0 must be an object",
        ),
    ],
)
def test_csl_json_rejects_invalid_shapes(text: str, message: str) -> None:
    with pytest.raises(BibliographyParseError, match=message):
        parse_csl_json(text)


def test_csl_json_fallbacks_cover_blank_id_names_published_year_and_lowercase_keys() -> None:
    raw = {
        "id": " ",
        "type": "book",
        "title": "Fallback Study",
        "author": [{}, {"given": "Ada"}, {"family": "Lovelace"}],
        "issued": {"date-parts": []},
        "published": "published 2021",
        "doi": "10.1000/fallback",
        "url": "https://example.test/fallback",
    }

    record = parse_csl_json(json.dumps(raw))[0]

    assert record.source_key.startswith("csl-json:0:")
    assert record.authors == ("Ada", "Lovelace")
    assert record.year == 2021
    assert record.doi == "10.1000/fallback"
    assert record.url == "https://example.test/fallback"


def test_csl_json_float_id_and_empty_items_are_supported() -> None:
    record = parse_csl_json(
        json.dumps({"id": 2.5, "type": "book", "title": "Numeric"})
    )[0]

    assert record.source_key == "2.5"
    assert parse_csl_json('{"items": []}') == ()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-an-object",
        {},
        {"date-parts": "2024"},
        {"date-parts": []},
        {"date-parts": ["2024"]},
        {"date-parts": [[]]},
    ],
)
def test_csl_year_rejects_incomplete_date_shapes(value: object) -> None:
    assert bibliography_csl_json._csl_year(value) is None


def test_ris_uses_fallback_tags_for_title_identity_author_year_and_url() -> None:
    record = parse_ris(
        "TY  -   \n"
        "CT  - Fallback title\n"
        "A1  - Ada Lovelace\n"
        "A1  -   \n"
        "DA  - 2020/01/02\n"
        "L2  - https://example.test/paper\n"
        "ER  -\n"
    )[0]

    assert record.title == "Fallback title"
    assert record.entry_type == "unknown"
    assert record.source_key.startswith("ris:0:")
    assert record.authors == ("Ada Lovelace",)
    assert record.year == 2020
    assert record.url == "https://example.test/paper"


@pytest.mark.parametrize("title_tag", ["T1", "CT", "BT"])
def test_ris_title_fallback_order(title_tag: str) -> None:
    record = parse_ris(f"TY  - JOUR\n{title_tag}  - Alternate\nER  -\n")[0]

    assert record.title == "Alternate"


@pytest.mark.parametrize("url_tag", ["UR", "L1", "L2"])
def test_ris_url_fallback_order(url_tag: str) -> None:
    record = parse_ris(
        f"TY  - JOUR\nTI  - Study\n{url_tag}  - https://example.test/x\nER  -\n"
    )[0]

    assert record.url == "https://example.test/x"


@pytest.mark.parametrize("year_tag", ["PY", "Y1", "DA"])
def test_ris_year_fallback_order(year_tag: str) -> None:
    record = parse_ris(f"TY  - JOUR\nTI  - Study\n{year_tag}  - 2019\nER  -\n")[0]

    assert record.year == 2019


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("TY  - JOUR\nTY  - BOOK\n", "starts a record before previous ER"),
        ("TI  - Outside\n", "appears outside a TY/ER record"),
        ("ER  -\n", "appears outside a TY/ER record"),
        ("not a tagged line\n", "invalid RIS line"),
        ("TY  - JOUR\nER  -\n", "has no title"),
    ],
)
def test_ris_rejects_state_machine_and_content_errors(text: str, message: str) -> None:
    with pytest.raises(BibliographyParseError, match=message):
        parse_ris(text)


def test_common_helpers_cover_stable_key_and_year_boundaries() -> None:
    key = bibliography_common.stable_key("x", 3, {"b": 2, "a": 1})
    assert key.startswith("x:3:")

    with pytest.raises(BibliographyParseError, match="not deterministically serializable"):
        bibliography_common.stable_key("x", 0, {"bad": {1, 2}})

    assert bibliography_common.year(None) is None
    assert bibliography_common.year(0) == 0
    assert bibliography_common.year(9999) == 9999
    assert bibliography_common.year(-1) is None
    assert bibliography_common.year(10000) is None
    assert bibliography_common.year("published 1998-01-01") == 1998
    assert bibliography_common.year("unknown") is None
    assert bibliography_common.optional_text("  value  ") == "value"
    assert bibliography_common.optional_text(42) is None


def test_parse_bibliography_file_and_suffix_dispatch(tmp_path: Path) -> None:
    ris = tmp_path / "refs.ris"
    ris.write_text("TY  - JOUR\nTI  - File Study\nER  -\n", encoding="utf-8")

    assert parse_bibliography(ris)[0].title == "File Study"

    with pytest.raises(FileNotFoundError):
        parse_bibliography(tmp_path / "missing.bib")

    assert parse_bibliography_bytes(
        "refs.bib",
        b"\xef\xbb\xbf@article{one, title={BOM Study}}",
    )[0].title == "BOM Study"
    assert parse_bibliography_bytes(
        "refs.json",
        b'{"id":"one","type":"book","title":"JSON Study"}',
    )[0].title == "JSON Study"
    assert parse_bibliography_bytes(
        "refs.csljson",
        b'{"id":"one","type":"book","title":"CSL Study"}',
    )[0].title == "CSL Study"
    assert parse_bibliography_bytes(
        "refs.csl-json",
        b'{"id":"one","type":"book","title":"CSL Dash Study"}',
    )[0].title == "CSL Dash Study"

    with pytest.raises(BibliographyParseError, match="unsupported bibliography format"):
        parse_bibliography_bytes("refs.txt", b"plain text")
