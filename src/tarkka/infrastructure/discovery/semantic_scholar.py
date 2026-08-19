from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tarkka.domain.discovery import DiscoveryPage, DiscoveryRecord, ResearchQuery
from tarkka.domain.identifiers import normalize_doi
from tarkka.infrastructure.discovery.http import JsonTransport, UrllibJsonTransport


class SemanticScholarProvider:
    name = "semantic-scholar"
    _URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    _FIELDS = "title,year,abstract,url,externalIds,citationCount,openAccessPdf"
    _MAX_LIMIT = 100

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
            "query": query.text.replace("-", " "),
            "limit": min(query.limit, self._MAX_LIMIT),
            "fields": self._FIELDS,
        }
        if query.cursor:
            try:
                offset = int(query.cursor)
            except ValueError as exc:
                raise ValueError(
                    f"Semantic Scholar cursor must be an integer offset: {query.cursor!r}"
                ) from exc
            if offset < 0:
                raise ValueError("Semantic Scholar cursor must be non-negative")
            params["offset"] = offset
        if query.year_from or query.year_to:
            start = str(query.year_from or "")
            end = str(query.year_to or "")
            # Official Graph API accepts 2016-2020, 2010-, and -2015.
            if start and end:
                params["year"] = f"{start}-{end}"
            elif start:
                params["year"] = f"{start}-"
            else:
                params["year"] = f"-{end}"
        if query.require_open_access:
            params["openAccessPdf"] = ""
        headers = {"x-api-key": self._api_key} if self._api_key else None
        payload = self._transport.get_json(self._URL, params=params, headers=headers)
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise ValueError("Semantic Scholar data must be a list")
        records = tuple(_record(item) for item in data if isinstance(item, Mapping))
        next_offset = payload.get("next")
        total = payload.get("total")
        return DiscoveryPage(
            provider=self.name,
            records=records,
            next_cursor=str(next_offset) if isinstance(next_offset, int) else None,
            total=total if isinstance(total, int) else None,
        )


def _record(raw: Mapping[str, Any]) -> DiscoveryRecord:
    paper_id = raw.get("paperId")
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("Semantic Scholar record must include paperId")

    external = raw.get("externalIds", {})
    external_map = external if isinstance(external, Mapping) else {}
    doi = external_map.get("DOI")
    doi_text = normalize_doi(doi) if isinstance(doi, str) and doi.strip() else None
    oa = raw.get("openAccessPdf", {})
    oa_map = oa if isinstance(oa, Mapping) else {}
    cited_by = raw.get("citationCount")
    external_ids = {
        str(key): str(value) for key, value in external_map.items() if value is not None
    }
    return DiscoveryRecord(
        provider="semantic-scholar",
        provider_id=paper_id,
        title=str(raw.get("title") or "Untitled"),
        year=raw.get("year") if isinstance(raw.get("year"), int) else None,
        doi=doi_text,
        abstract=raw.get("abstract") if isinstance(raw.get("abstract"), str) else None,
        landing_page_url=raw.get("url") if isinstance(raw.get("url"), str) else None,
        open_access_url=oa_map.get("url") if isinstance(oa_map.get("url"), str) else None,
        cited_by_count=cited_by if isinstance(cited_by, int) else None,
        external_ids=external_ids,
    )
