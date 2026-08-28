from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import UTC, datetime
from email.message import Message
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree

import pytest

from tarkka.domain.discovery import ResearchQuery
from tarkka.infrastructure.discovery import arxiv, http
from tarkka.infrastructure.discovery.arxiv import ArxivProvider, UrllibAtomTransport
from tarkka.infrastructure.discovery.crossref import CrossrefProvider
from tarkka.infrastructure.discovery.openalex import OpenAlexProvider
from tarkka.infrastructure.discovery.semantic_scholar import SemanticScholarProvider

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _JsonTransport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.last_url = ""
        self.last_params: Mapping[str, str | int | bool] = {}
        self.last_headers: Mapping[str, str] | None = None

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.last_url = url
        self.last_params = params or {}
        self.last_headers = headers
        return self.payload


class _AtomTransport:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.params: Mapping[str, str | int] = {}

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str] | None = None,
    ) -> str:
        del url, headers
        self.params = params
        return self.payload


def _atom_entry(*, published: str = "bad", include_pdf: bool = False) -> ElementTree.Element:
    pdf = (
        '<link title="pdf" type="application/pdf" href="http://arxiv.org/pdf/2401.00001" />'
        if include_pdf
        else '<link title="pdf" type="application/pdf" />'
    )
    return ElementTree.fromstring(
        f'''<entry xmlns="http://www.w3.org/2005/Atom"
            xmlns:arxiv="http://arxiv.org/schemas/atom">
          <id>http://arxiv.org/abs/2401.00001v1</id>
          <published>{published}</published>
          <title> Edge   Paper </title>
          <summary> Sparse summary. </summary>
          <category />
          {pdf}
        </entry>'''
    )


def test_urllib_atom_transport_validates_timeout_and_decodes_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        UrllibAtomTransport(timeout_seconds=0)

    observed: dict[str, object] = {}

    def fake_urlopen(request: object, *, timeout: float) -> io.BytesIO:
        observed["request"] = request
        observed["timeout"] = timeout
        return io.BytesIO(b"<feed />")

    monkeypatch.setattr(arxiv, "urlopen", fake_urlopen)
    transport = UrllibAtomTransport(timeout_seconds=2.5)

    assert transport.get_text(
        "https://example.test/api",
        params={"q": "a b"},
        headers={"X-Test": "yes"},
    ) == "<feed />"
    request = observed["request"]
    assert getattr(request, "full_url").endswith("?q=a+b")
    assert observed["timeout"] == 2.5


def test_urllib_atom_transport_rejects_non_bytes_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self) -> str:
            return "not-bytes"

    monkeypatch.setattr(arxiv, "urlopen", lambda request, timeout: _Response())

    with pytest.raises(TypeError, match="response body must be bytes"):
        UrllibAtomTransport().get_text("https://example.test", params={})


def test_arxiv_query_cursor_and_helper_boundaries() -> None:
    with pytest.raises(ValueError, match="at least one term"):
        arxiv._all_fields_expression("   ")
    with pytest.raises(ValueError, match="non-negative integer"):
        arxiv._cursor_start("abc")
    with pytest.raises(ValueError, match="non-negative integer"):
        arxiv._cursor_start("-1")

    assert arxiv._cursor_start(None) == 0
    assert arxiv._all_fields_expression('one "two three"') == (
        'all:"one" AND all:"two three"'
    )
    assert "submittedDate:[190001010000 TO 202012312359]" in arxiv._search_query(
        ResearchQuery("term", year_to=2020)
    )
    assert "submittedDate:[202001010000 TO " in arxiv._search_query(
        ResearchQuery("term", year_from=2020)
    )


def test_arxiv_record_sparse_metadata_and_helpers() -> None:
    record = arxiv._record(_atom_entry())

    assert record.year is None
    assert record.doi is None
    assert record.open_access_url is None
    assert record.external_ids == {"arxiv": "2401.00001"}
    assert record.metadata["categories"] == []
    assert record.metadata["primary_category"] is None

    assert arxiv._pdf_url(_atom_entry(include_pdf=True)) == (
        "https://arxiv.org/pdf/2401.00001"
    )
    assert arxiv._text(None) is None
    assert arxiv._text(ElementTree.Element("x")) is None
    blank = ElementTree.Element("x")
    blank.text = "   "
    assert arxiv._text(blank) is None
    assert arxiv._year(None) is None
    assert arxiv._year("123") is None
    assert arxiv._year("abcd-01-01") is None
    assert arxiv._int_text(None) is None
    bad_int = ElementTree.Element("x")
    bad_int.text = "not-an-int"
    assert arxiv._int_text(bad_int) is None
    with pytest.raises(ValueError, match="must be present"):
        arxiv._required_text(None, "field")


def test_arxiv_search_without_total_has_no_next_cursor() -> None:
    payload = '''<feed xmlns="http://www.w3.org/2005/Atom"></feed>'''
    page = ArxivProvider(_AtomTransport(payload)).search(ResearchQuery("term"))

    assert page.total is None
    assert page.records == ()
    assert page.next_cursor is None


def test_crossref_filters_bad_shapes_and_skips_non_objects() -> None:
    transport = _JsonTransport(
        {"message": {"items": ["skip"], "next-cursor": "", "total-results": "1"}}
    )
    page = CrossrefProvider(transport).search(
        ResearchQuery(
            "query",
            year_from=2010,
            year_to=2020,
            require_open_access=True,
        )
    )

    assert page.records == ()
    assert page.next_cursor is None
    assert page.total is None
    assert transport.last_params["filter"] == (
        "from-pub-date:2010-01-01,until-pub-date:2020-12-31,"
        "assertion:free,has-full-text:true"
    )

    with pytest.raises(ValueError, match="message must be an object"):
        CrossrefProvider(_JsonTransport({"message": []})).search(ResearchQuery("q"))
    with pytest.raises(ValueError, match="items must be a list"):
        CrossrefProvider(_JsonTransport({"message": {"items": {}}})).search(
            ResearchQuery("q")
        )


def test_crossref_lookup_rejects_bad_message_and_mismatched_doi() -> None:
    with pytest.raises(ValueError, match="work response message must be an object"):
        CrossrefProvider(_JsonTransport({"message": []})).lookup_by_doi("10.1/test")

    transport = _JsonTransport(
        {"message": {"DOI": "10.2/other", "title": ["Other"], "URL": "https://x"}}
    )
    with pytest.raises(ValueError, match="different DOI"):
        CrossrefProvider(transport).lookup_by_doi("10.1/test")


def test_crossref_record_identifier_metadata_and_date_fallbacks() -> None:
    raw: dict[str, Any] = {
        "title": "not-a-list",
        "URL": "https://example.test/work",
        "abstract": 42,
        "is-referenced-by-count": "many",
        "ISBN": "978-one",
        "ISSN": ["1234", 5678, None, {}],
        "PMID": [],
        "PMCID": [None, {}],
        "alternative-id": "ALT",
        "type": "",
        "container-title": "not-a-list",
        "published-print": "bad",
        "published-online": {"date-parts": []},
        "published": {"date-parts": [[]]},
        "issued": {"date-parts": [[2018]]},
    }
    record = CrossrefProvider(_JsonTransport({"message": {"items": [raw]}})).search(
        ResearchQuery("q")
    ).records[0]

    assert record.provider_id == "https://example.test/work"
    assert record.title == "Untitled"
    assert record.abstract is None
    assert record.cited_by_count is None
    assert record.year == 2018
    assert record.external_ids["isbn"] == "978-one"
    assert record.external_ids["issn"] == '["1234","5678"]'
    assert record.external_ids["alternative-id"] == "ALT"
    assert "pmid" not in record.external_ids
    assert "pmcid" not in record.external_ids
    assert record.metadata == {}


def test_openalex_filters_payload_shapes_and_record_fallbacks() -> None:
    transport = _JsonTransport(
        {
            "meta": "bad-meta",
            "results": [
                "skip",
                {
                    "id": "https://openalex.org/W9",
                    "title": "Fallback title",
                    "publication_year": "2020",
                    "cited_by_count": "many",
                    "ids": {"openalex": "W9", "none": None},
                    "primary_location": "bad",
                    "open_access": "bad",
                },
            ],
        }
    )
    page = OpenAlexProvider(transport, api_key="key").search(
        ResearchQuery(
            "query",
            year_from=2010,
            year_to=2020,
            require_open_access=True,
        )
    )

    assert page.next_cursor is None
    assert page.total is None
    assert page.records[0].title == "Fallback title"
    assert page.records[0].year is None
    assert page.records[0].cited_by_count is None
    assert page.records[0].external_ids == {"openalex": "W9"}
    assert transport.last_params["filter"] == (
        "is_oa:true,from_publication_date:2010-01-01,to_publication_date:2020-12-31"
    )
    assert transport.last_params["api_key"] == "key"

    with pytest.raises(ValueError, match="results must be a list"):
        OpenAlexProvider(_JsonTransport({"results": {}})).search(ResearchQuery("q"))
    with pytest.raises(ValueError, match="include id"):
        OpenAlexProvider(_JsonTransport({"results": [{"id": "   "}]})).search(
            ResearchQuery("q")
        )
    with pytest.raises(ValueError, match="stable identifier"):
        OpenAlexProvider(_JsonTransport({"results": [{"id": "/"}]})).search(
            ResearchQuery("q")
        )


def test_semantic_scholar_cursor_open_access_and_payload_fallbacks() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        SemanticScholarProvider(_JsonTransport({"data": []})).search(
            ResearchQuery("q", cursor="-1")
        )

    transport = _JsonTransport(
        {
            "total": "many",
            "next": "next",
            "data": [
                "skip",
                {
                    "paperId": "S2",
                    "externalIds": "bad",
                    "openAccessPdf": "bad",
                    "title": "",
                    "year": "2020",
                    "abstract": 42,
                    "url": 42,
                    "citationCount": "many",
                },
            ],
        }
    )
    page = SemanticScholarProvider(transport).search(
        ResearchQuery("q", require_open_access=True)
    )

    assert transport.last_params["openAccessPdf"] == ""
    assert transport.last_headers is None
    assert page.next_cursor is None
    assert page.total is None
    record = page.records[0]
    assert record.title == "Untitled"
    assert record.year is None
    assert record.abstract is None
    assert record.landing_page_url is None
    assert record.open_access_url is None
    assert record.cited_by_count is None
    assert record.external_ids == {}
    assert record.metadata == {}

    with pytest.raises(ValueError, match="data must be a list"):
        SemanticScholarProvider(_JsonTransport({"data": {}})).search(ResearchQuery("q"))
    with pytest.raises(ValueError, match="paperId"):
        SemanticScholarProvider(_JsonTransport({"data": [{"paperId": "   "}]})).search(
            ResearchQuery("q")
        )


def test_http_transport_terminal_errors_and_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPError):
        monkeypatch.setattr(
            http,
            "urlopen",
            lambda request, timeout: (_ for _ in ()).throw(
                HTTPError("https://x", 400, "bad", Message(), None)
            ),
        )
        http.UrllibJsonTransport(max_retries=2).get_json("https://x")

    monkeypatch.setattr(
        http,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(URLError("down")),
    )
    with pytest.raises(URLError):
        http.UrllibJsonTransport(max_retries=0).get_json("https://x")

    moments = iter((0.0, 1.0))
    with pytest.raises(TimeoutError, match="exceeded total timeout") as raised:
        http.UrllibJsonTransport(
            timeout_seconds=1,
            total_timeout_seconds=0.5,
            monotonic=lambda: next(moments),
        ).get_json("https://x")
    assert raised.value.__cause__ is None


def test_http_transport_non_object_json_and_timeout_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http, "urlopen", lambda request, timeout: io.BytesIO(b"[]"))
    with pytest.raises(ValueError, match="JSON object"):
        http.UrllibJsonTransport(max_retries=0).get_json("https://x")

    monkeypatch.setattr(
        http,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(URLError("temporary")),
    )
    moments = iter((0.0, 0.1, 2.0))
    with pytest.raises(TimeoutError, match="exceeded total timeout") as raised:
        http.UrllibJsonTransport(
            timeout_seconds=1,
            max_retries=1,
            total_timeout_seconds=1,
            monotonic=lambda: next(moments),
            sleep=lambda delay: None,
        ).get_json("https://x")
    assert isinstance(raised.value.__cause__, URLError)


def test_http_retry_helper_boundaries() -> None:
    assert http._retryable_status(429) is True
    assert http._retryable_status(503) is True
    assert http._retryable_status(418) is False
    assert http._jittered_backoff(3, 0.0, lambda low, high: 99.0) == 0.0

    headers = Message()
    headers["Retry-After"] = "-2"
    assert http._retry_delay(
        0,
        headers,
        1,
        now=lambda: datetime.now(UTC),
        jitter=lambda low, high: high,
    ) == 0.0

    malformed = Message()
    malformed["Retry-After"] = "not-a-date"
    assert http._retry_delay(
        1,
        malformed,
        0.5,
        now=lambda: datetime.now(UTC),
        jitter=lambda low, high: high,
    ) == 1.0

    date_header = Message()
    date_header["Retry-After"] = "Wed, 21 Oct 2015 07:28:10"
    assert http._retry_delay(
        0,
        date_header,
        1,
        now=lambda: datetime(2015, 10, 21, 7, 28),
        jitter=lambda low, high: high,
    ) == 10.0
