from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from tarkka.domain.discovery import DiscoveryPage, DiscoveryRecord, ResearchQuery
from tarkka.domain.identifiers import try_normalize_doi

_ATOM = "{http://www.w3.org/2005/Atom}"
_OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


class AtomTransport(Protocol):
    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str] | None = None,
    ) -> str: ...


class UrllibAtomTransport:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str] | None = None,
    ) -> str:
        target = f"{url}?{urlencode(params)}"
        request = Request(target, headers=dict(headers or {}))
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            return response.read().decode("utf-8")


class ArxivProvider:
    name = "arxiv"
    _URL = "https://export.arxiv.org/api/query"
    _MAX_RESULTS = 200

    def __init__(
        self,
        transport: AtomTransport | None = None,
        *,
        user_agent: str = "tarkka/0.1 (+https://github.com/cbwinslow/Tarkka)",
    ) -> None:
        self._transport = transport or UrllibAtomTransport()
        self._user_agent = user_agent

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        start = _cursor_start(query.cursor)
        page_size = min(query.limit, self._MAX_RESULTS)
        params: dict[str, str | int] = {
            "search_query": _search_query(query),
            "start": start,
            "max_results": page_size,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        payload = self._transport.get_text(
            self._URL,
            params=params,
            headers={"User-Agent": self._user_agent},
        )
        root = ElementTree.fromstring(payload)
        total = _int_text(root.find(f"{_OPENSEARCH}totalResults"))
        records = tuple(_record(entry) for entry in root.findall(f"{_ATOM}entry"))
        consumed = start + len(records)
        next_cursor = str(consumed) if total is not None and consumed < total else None
        return DiscoveryPage(
            provider=self.name,
            records=records,
            next_cursor=next_cursor,
            total=total,
        )


def _search_query(query: ResearchQuery) -> str:
    text = " ".join(query.text.split())
    expression = f'all:"{text.replace(chr(34), "")}"'
    if query.year_from is None and query.year_to is None:
        return expression
    lower_year = query.year_from or 1900
    upper_year = query.year_to or datetime.now().year
    return (
        f"{expression} AND submittedDate:"
        f"[{lower_year:04d}01010000 TO {upper_year:04d}12312359]"
    )


def _cursor_start(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        start = int(cursor)
    except ValueError as exc:
        raise ValueError("arXiv cursor must be a non-negative integer") from exc
    if start < 0:
        raise ValueError("arXiv cursor must be a non-negative integer")
    return start


def _record(entry: ElementTree.Element) -> DiscoveryRecord:
    raw_id = _required_text(entry.find(f"{_ATOM}id"), "arXiv entry id")
    provider_id = raw_id.rstrip("/").rsplit("/", 1)[-1]
    title = _clean_text(_required_text(entry.find(f"{_ATOM}title"), "arXiv title"))
    abstract = _clean_text(_required_text(entry.find(f"{_ATOM}summary"), "arXiv summary"))
    published = _text(entry.find(f"{_ATOM}published"))
    doi = try_normalize_doi(_text(entry.find(f"{_ARXIV}doi")))
    pdf_url = _pdf_url(entry)
    categories = [
        term
        for category in entry.findall(f"{_ATOM}category")
        if (term := category.attrib.get("term"))
    ]
    primary = entry.find(f"{_ARXIV}primary_category")
    primary_category = primary.attrib.get("term") if primary is not None else None
    external_ids: dict[str, str] = {"arxiv": provider_id}
    if doi:
        external_ids["doi"] = doi
    return DiscoveryRecord(
        provider="arxiv",
        provider_id=provider_id,
        title=title,
        year=_year(published),
        doi=doi,
        abstract=abstract,
        landing_page_url=raw_id.replace("http://", "https://"),
        open_access_url=pdf_url,
        external_ids=external_ids,
        metadata={
            "categories": categories,
            "primary_category": primary_category,
            "publication_type": "preprint",
        },
    )


def _pdf_url(entry: ElementTree.Element) -> str | None:
    for link in entry.findall(f"{_ATOM}link"):
        if link.attrib.get("type") == "application/pdf" or link.attrib.get("title") == "pdf":
            href = link.attrib.get("href")
            if href:
                return href.replace("http://", "https://")
    return None


def _required_text(element: ElementTree.Element | None, field: str) -> str:
    value = _text(element)
    if not value:
        raise ValueError(f"{field} must be present")
    return value


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _year(value: str | None) -> int | None:
    if value is None or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _int_text(element: ElementTree.Element | None) -> int | None:
    value = _text(element)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
