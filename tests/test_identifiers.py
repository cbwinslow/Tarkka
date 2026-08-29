from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import pytest

from tarkka.domain.identifiers import (
    artifact_id_from_sha256,
    normalize_arxiv_id,
    normalize_doi,
    try_normalize_arxiv_id,
    try_normalize_doi,
)


def test_artifact_id_from_sha256_is_stable_and_content_derived() -> None:
    digest = "a" * 64

    assert artifact_id_from_sha256(digest) == uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    assert artifact_id_from_sha256(digest) == artifact_id_from_sha256(digest)
    assert artifact_id_from_sha256("b" * 64) != artifact_id_from_sha256(digest)


@pytest.mark.parametrize("value", ["", "A" * 64, "g" * 64, "a" * 63, None])
def test_artifact_id_from_sha256_rejects_noncanonical_digests(value: object) -> None:
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        artifact_id_from_sha256(value)  # type: ignore[arg-type]


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


def test_try_normalize_doi_returns_canonical_value_for_valid_input() -> None:
    assert try_normalize_doi(" DOI:10.1234/ABC ") == "10.1234/abc"


def test_try_normalize_doi_returns_none_for_untrusted_malformed_values() -> None:
    assert try_normalize_doi(None) is None
    assert try_normalize_doi("doi:") is None
    assert try_normalize_doi("not-a-doi") is None


def test_normalize_arxiv_id_accepts_common_forms_and_removes_versions() -> None:
    assert normalize_arxiv_id(" arXiv:2401.12345v2 ") == "2401.12345"
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.12345v3") == "2401.12345"
    assert normalize_arxiv_id("https://arxiv.org/pdf/hep-th/9901001v2.pdf") == "hep-th/9901001"


@pytest.mark.parametrize(
    "value",
    (
        "",
        "arxiv:",
        "not-an-arxiv-id",
        "2401.123",
        "2401.123456",
        "hep-th/123456",
    ),
)
def test_normalize_arxiv_id_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_arxiv_id(value)


def test_try_normalize_arxiv_id_handles_valid_and_untrusted_values() -> None:
    assert try_normalize_arxiv_id("arXiv:2401.12345v2") == "2401.12345"
    assert try_normalize_arxiv_id(None) is None
    assert try_normalize_arxiv_id("arxiv:") is None
    assert try_normalize_arxiv_id("not-an-arxiv-id") is None
