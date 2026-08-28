from __future__ import annotations

from typing import Any

import pytest

from tarkka.domain.bibliography import BibliographyFormat, BibliographyRecord
from tarkka.domain.discovery import (
    DiscoveryRecord,
    ProviderMode,
    ResearchQuery,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _bibliography_record(**overrides: Any) -> BibliographyRecord:
    values: dict[str, Any] = {
        "source_format": BibliographyFormat.BIBTEX,
        "source_key": "smith2024",
        "entry_type": "article",
        "title": "Example",
    }
    values.update(overrides)
    return BibliographyRecord(**values)


@pytest.mark.parametrize(
    ("field_name", "message"),
    [
        ("source_key", "source key"),
        ("entry_type", "entry type"),
        ("title", "title"),
    ],
)
def test_bibliography_record_rejects_blank_required_fields(
    field_name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _bibliography_record(**{field_name: " "})


@pytest.mark.parametrize(
    "source_scope",
    ["", "a" * 63, "g" * 64],
)
def test_bibliography_record_requires_sha256_source_scope(source_scope: str) -> None:
    with pytest.raises(ValueError, match="source_scope must be a SHA-256"):
        _bibliography_record().to_discovery_record(source_scope)


def test_bibliography_record_maps_format_specific_publication_types() -> None:
    scope = "a" * 64

    bibtex = _bibliography_record(entry_type="InProceedings").to_discovery_record(scope)
    ris = _bibliography_record(
        source_format=BibliographyFormat.RIS,
        entry_type="jour",
    ).to_discovery_record(scope)
    csl = _bibliography_record(
        source_format=BibliographyFormat.CSL_JSON,
        entry_type="paper-conference",
    ).to_discovery_record(scope)

    assert bibtex.metadata["publication_type"] == "conference-paper"
    assert ris.metadata["publication_type"] == "article"
    assert csl.metadata["publication_type"] == "conference-paper"


def test_bibliography_record_preserves_unknown_publication_type_normalized() -> None:
    scope = "A" * 64
    record = _bibliography_record(
        source_format=BibliographyFormat.RIS,
        entry_type="CustomType",
    ).to_discovery_record(scope)

    assert record.provider_id.startswith("a" * 64)
    assert record.metadata["publication_type"] == "customtype"


@pytest.mark.parametrize("text", ["", "   "])
def test_research_query_rejects_blank_text(text: str) -> None:
    with pytest.raises(ValueError, match="query must not be blank"):
        ResearchQuery(text=text)


@pytest.mark.parametrize("limit", [0, 1001])
def test_research_query_enforces_limit_bounds(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
        ResearchQuery(text="query", limit=limit)


def test_research_query_only_mode_requires_provider() -> None:
    with pytest.raises(ValueError, match="mode=only"):
        ResearchQuery(text="query", mode=ProviderMode.ONLY)


def test_research_query_rejects_inverted_year_bounds() -> None:
    with pytest.raises(ValueError, match="year_from must be <= year_to"):
        ResearchQuery(text="query", year_from=2025, year_to=2024)


def test_research_query_rejects_global_and_provider_cursors_together() -> None:
    with pytest.raises(ValueError, match="either cursor or provider-keyed cursors"):
        ResearchQuery(text="query", cursor="global", cursors={"openalex": "provider"})


@pytest.mark.parametrize(
    ("provider", "provider_id"),
    [("", "id"), ("provider", " ")],
)
def test_discovery_record_requires_provider_identity(
    provider: str,
    provider_id: str,
) -> None:
    with pytest.raises(ValueError, match="provider and provider_id"):
        DiscoveryRecord(provider=provider, provider_id=provider_id, title="Paper")


def test_discovery_record_requires_title() -> None:
    with pytest.raises(ValueError, match="title must not be blank"):
        DiscoveryRecord(provider="provider", provider_id="id", title=" ")
