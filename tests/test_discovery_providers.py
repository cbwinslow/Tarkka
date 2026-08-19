from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tarkka.domain.discovery import ResearchQuery
from tarkka.infrastructure.discovery.crossref import CrossrefProvider
from tarkka.infrastructure.discovery.openalex import OpenAlexProvider
from tarkka.infrastructure.discovery.semantic_scholar import SemanticScholarProvider


class _Transport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.last_url = ""
        self.last_params: Mapping[str, str | int | bool] = {}
        self.last_headers: Mapping[str, str] = {}

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.last_url = url
        self.last_params = params or {}
        self.last_headers = headers or {}
        return self.payload


def test_openalex_maps_work_and_cursor() -> None:
    transport = _Transport(
        {
            "meta": {"count": 12, "next_cursor": "next"},
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "MLB prediction",
                    "publication_year": 2024,
                    "doi": "https://doi.org/10.1234/ABC",
                    "ids": {"openalex": "https://openalex.org/W123"},
                    "cited_by_count": 9,
                    "primary_location": {"landing_page_url": "https://example.test/paper"},
                    "open_access": {"oa_url": "https://example.test/paper.pdf"},
                }
            ],
        }
    )

    page = OpenAlexProvider(transport).search(ResearchQuery("mlb prediction"))

    assert page.next_cursor == "next"
    assert page.total == 12
    assert page.records[0].provider_id == "W123"
    assert page.records[0].doi == "10.1234/abc"
    assert transport.last_params["cursor"] == "*"


def test_crossref_maps_doi_metadata() -> None:
    transport = _Transport(
        {
            "message": {
                "total-results": 1,
                "next-cursor": "cursor-2",
                "items": [
                    {
                        "DOI": "10.5555/XYZ",
                        "title": ["Baseball model"],
                        "URL": "https://doi.org/10.5555/XYZ",
                        "published": {"date-parts": [[2022, 1, 1]]},
                        "is-referenced-by-count": 4,
                    }
                ],
            }
        }
    )

    page = CrossrefProvider(transport, mailto="researcher@example.test").search(
        ResearchQuery("baseball model", limit=50)
    )

    assert page.records[0].doi == "10.5555/xyz"
    assert page.records[0].year == 2022
    assert transport.last_params["cursor"] == "*"
    assert transport.last_params["mailto"] == "researcher@example.test"


def test_semantic_scholar_maps_search_result_and_api_key() -> None:
    transport = _Transport(
        {
            "total": 3,
            "next": 10,
            "data": [
                {
                    "paperId": "S2-1",
                    "title": "Win probability",
                    "year": 2023,
                    "abstract": "An abstract",
                    "url": "https://example.test/s2",
                    "externalIds": {"DOI": "10.9999/TEST"},
                    "citationCount": 8,
                    "openAccessPdf": {"url": "https://example.test/open.pdf"},
                }
            ],
        }
    )

    page = SemanticScholarProvider(transport, api_key="secret").search(
        ResearchQuery("win-probability")
    )

    assert page.next_cursor == "10"
    assert page.records[0].doi == "10.9999/test"
    assert transport.last_headers["x-api-key"] == "secret"
    assert transport.last_params["query"] == "win probability"
