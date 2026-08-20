from __future__ import annotations

import pytest

from tarkka.domain.identifiers import normalize_doi, try_normalize_doi


def test_normalize_doi_accepts_common_and_nested_prefixes() -> None:
    assert normalize_doi(" DOI:10.1234/ABC ") == "10.1234/abc"
    assert normalize_doi("https://doi.org/10.56789/Test_1") == "10.56789/test_1"
    assert normalize_doi("https://doi.org/doi:10.1234/abc") == "10.1234/abc"


@pytest.mark.parametrize(
    "value",
    (
        "",
        "doi:",
        "not-a-doi",
        "10.1234/",
        "10.123 /abc",
        "10.1234 /abc",
    ),
)
def test_normalize_doi_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_doi(value)


def test_try_normalize_doi_returns_none_for_untrusted_malformed_values() -> None:
    assert try_normalize_doi(None) is None
    assert try_normalize_doi("doi:") is None
    assert try_normalize_doi("not-a-doi") is None
