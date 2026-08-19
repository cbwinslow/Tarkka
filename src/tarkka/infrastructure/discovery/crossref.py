from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tarkka.domain.discovery import DiscoveryPage, DiscoveryRecord, ResearchQuery
from tarkka.domain.identifiers import normalize_doi
from tarkka.infrastructure.discovery.http import JsonTransport, UrllibJsonTransport


class CrossrefProvider:
    name = "crossref"
    _URL = "https://api.crossref.org/works"

    def __init__(
        self,
        transport: JsonTransport | None = None,
        *,
        mailto: str | None = None,
    ) -> None:
        self._transport = transport or UrllibJsonTransport()
        self._mailto = mailto

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        params: dict[str, str | int | bool] = {
            "query.bibliographic": query.text,
            "rows": query.limit,
        }
        if query.cursor:
            params["cursor"] = query.cursor
        elif query.limit > 20:
            params["cursor"] = "*"
        if self._mailto:
            params["mailto"] = self._mailto
        filters: list[str] = []
        if query.year_from:
            filters.append(f"from-pub-date:{query.year_from}-01-01")
        if query.year_to:
            filters.append(f"until-pub-date:{query.year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)

        payload = self._transport.get_json(self._URL, params=params)
        message = payload.get("message", {})
        if not isinstance(message, Mapping):
            raise ValueError("Crossref message must be an object")
        items = message.get("items", [])
        if not isinstance(items, list):
            raise ValueError("Crossref items must be a list")
        records = tuple(_record(item) for item in items if isinstance(item, Mapping))
        next_cursor = message.get("next-cursor")
        total = message.get("total-results")
        return DiscoveryPage(
            provider=self.name,
            records=records,
            next_cursor=str(next_cursor) if next_cursor else None,
            total=total if isinstance(total, int) else None,
        )


def _record(raw: Mapping[str, Any]) -> DiscoveryRecord:
    doi = raw.get("DOI")
    doi_text = normalize_doi(doi) if isinstance(doi, str) and doi.strip() else None
    title = raw.get("title", [])
    title_text = (
        title[0]
        if isinstance(title, list) and title and isinstance(title[0], str)
        else "Untitled"
    )
    url = raw.get("URL") if isinstance(raw.get("URL"), str) else None
    cited_by = raw.get("is-referenced-by-count")
    provider_id = doi_text or url or "unknown"
    return DiscoveryRecord(
        provider="crossref",
        provider_id=provider_id,
        title=title_text,
        year=_published_year(raw),
        doi=doi_text,
        abstract=raw.get("abstract") if isinstance(raw.get("abstract"), str) else None,
        landing_page_url=url,
        cited_by_count=cited_by if isinstance(cited_by, int) else None,
        external_ids=_external_ids(raw, doi_text),
    )


def _external_ids(raw: Mapping[str, Any], doi: str | None) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    if doi:
        identifiers["doi"] = doi
    for key in ("ISBN", "ISSN", "PMID", "PMCID", "alternative-id"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            identifiers[key.lower()] = value
        elif isinstance(value, list):
            values = [str(item) for item in value if isinstance(item, (str, int))]
            if values:
                identifiers[key.lower()] = ",".join(values)
    return identifiers


def _published_year(raw: Mapping[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        value = raw.get(key)
        if not isinstance(value, Mapping):
            continue
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list):
            first = date_parts[0]
            if first and isinstance(first[0], int):
                return first[0]
    return None
