from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tarkka.domain.discovery import DiscoveryPage, DiscoveryRecord, ResearchQuery
from tarkka.infrastructure.discovery.http import JsonTransport, UrllibJsonTransport


class OpenAlexProvider:
    name = "openalex"
    _URL = "https://api.openalex.org/works"

    def __init__(
        self,
        transport: JsonTransport | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        self._transport = transport or UrllibJsonTransport()
        self._api_key = api_key

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        params: dict[str, str | int | bool] = {
            "search": query.text,
            "per-page": query.limit,
        }
        if query.cursor:
            params["cursor"] = query.cursor
        else:
            params["cursor"] = "*"
        filters: list[str] = []
        if query.require_open_access:
            filters.append("is_oa:true")
        if query.year_from:
            filters.append(f"from_publication_date:{query.year_from}-01-01")
        if query.year_to:
            filters.append(f"to_publication_date:{query.year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self._api_key:
            params["api_key"] = self._api_key

        payload = self._transport.get_json(self._URL, params=params)
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("OpenAlex results must be a list")
        records = tuple(_record(item) for item in raw_results if isinstance(item, Mapping))
        meta = payload.get("meta", {})
        next_cursor = meta.get("next_cursor") if isinstance(meta, Mapping) else None
        total = meta.get("count") if isinstance(meta, Mapping) else None
        return DiscoveryPage(
            provider=self.name,
            records=records,
            next_cursor=str(next_cursor) if next_cursor else None,
            total=int(total) if isinstance(total, int) else None,
        )


def _record(raw: Mapping[str, Any]) -> DiscoveryRecord:
    ids = raw.get("ids", {})
    ids_map = ids if isinstance(ids, Mapping) else {}
    doi = _doi(raw.get("doi"))
    primary = raw.get("primary_location", {})
    primary_map = primary if isinstance(primary, Mapping) else {}
    oa = raw.get("open_access", {})
    oa_map = oa if isinstance(oa, Mapping) else {}
    provider_id = str(raw.get("id", "")).rsplit("/", 1)[-1]
    return DiscoveryRecord(
        provider="openalex",
        provider_id=provider_id,
        title=str(raw.get("display_name") or raw.get("title") or "Untitled"),
        year=_int_or_none(raw.get("publication_year")),
        doi=doi,
        landing_page_url=_str_or_none(primary_map.get("landing_page_url")),
        open_access_url=_str_or_none(oa_map.get("oa_url")),
        cited_by_count=_int_or_none(raw.get("cited_by_count")),
        external_ids={
            str(key): str(value)
            for key, value in ids_map.items()
            if value is not None
        },
    )


def _doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.removeprefix("https://doi.org/").removeprefix("http://doi.org/").lower()


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
