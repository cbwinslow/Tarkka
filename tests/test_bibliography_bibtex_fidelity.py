from __future__ import annotations

import pytest

from tarkka.infrastructure.bibliography_interchange import BibliographyParseError, parse_bibtex


def test_bibtex_preserves_native_field_key_casing_with_case_insensitive_semantics() -> None:
    record = parse_bibtex(
        "@article{mixed, Title={Mixed Case Study}, AUTHOR={Smith, Jane}, "
        "CustomField={Preserve Me}}"
    )[0]

    assert record.title == "Mixed Case Study"
    assert record.authors == ("Smith, Jane",)
    assert record.fields["Title"] == "Mixed Case Study"
    assert record.fields["AUTHOR"] == "Smith, Jane"
    assert record.fields["CustomField"] == "Preserve Me"


def test_bibtex_rejects_fields_that_only_differ_by_case() -> None:
    with pytest.raises(BibliographyParseError, match="ambiguous case-insensitively"):
        parse_bibtex("@article{ambiguous, Title={One}, title={Two}}")


def test_parenthesized_bibtex_preserves_percent_inside_braced_value() -> None:
    record = parse_bibtex(
        "@article(paren-percent, title={Observed 50% response}, year={2024})"
    )[0]

    assert record.title == "Observed 50% response"
    assert record.year == 2024
