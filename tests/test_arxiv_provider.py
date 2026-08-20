from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from tarkka.domain.discovery import ResearchQuery
from tarkka.domain.identifiers import normalize_arxiv_id
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier
from tarkka.infrastructure.discovery.arxiv import ArxivProvider
from tarkka.infrastructure.full_text.arxiv import ArxivFullTextResolver


class _AtomTransport:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.params: Mapping[str, str | int] | None = None

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str] | None = None,
    ) -> str:
        assert url == "https://export.arxiv.org/api/query"
        assert headers is not None and "User-Agent" in headers
        self.params = params
        return self.payload


_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <published>2024-01-03T00:00:00Z</published>
    <title>  A   Baseball Prediction Model </title>
    <summary> We test a model. </summary>
    <author><name>Example Author</name></author>
    <arxiv:doi>https://doi.org/10.1234/EXAMPLE</arxiv:doi>
    <arxiv:primary_category term="stat.ML" />
    <category term="stat.ML" />
    <category term="cs.LG" />
    <link href="http://arxiv.org/abs/2401.01234v2" rel="alternate" type="text/html" />
    <link title="pdf" href="http://arxiv.org/pdf/2401.01234v2" rel="related"
          type="application/pdf" />
  </entry>
</feed>
"""


def test_arxiv_provider_parses_atom_and_emits_numeric_cursor() -> None:
    transport = _AtomTransport(_ATOM)
    page = ArxivProvider(transport).search(
        ResearchQuery("baseball prediction", limit=1, year_from=2020, year_to=2024)
    )

    assert page.provider == "arxiv"
    assert page.total == 2
    assert page.next_cursor == "1"
    assert len(page.records) == 1
    record = page.records[0]
    assert record.provider_id == "2401.01234"
    assert record.title == "A Baseball Prediction Model"
    assert record.year == 2024
    assert record.doi == "10.1234/example"
    assert record.open_access_url == "https://arxiv.org/pdf/2401.01234v2"
    assert record.external_ids["arxiv"] == "2401.01234"
    assert record.metadata["primary_category"] == "stat.ML"
    assert transport.params is not None
    assert transport.params["start"] == 0
    assert transport.params["max_results"] == 1
    assert "submittedDate:[202001010000 TO 202412312359]" in str(
        transport.params["search_query"]
    )


def test_arxiv_provider_uses_explicit_cursor() -> None:
    transport = _AtomTransport(_ATOM.replace("<opensearch:totalResults>2", "<opensearch:totalResults>7"))
    page = ArxivProvider(transport).search(ResearchQuery("test", limit=1, cursor="5"))

    assert transport.params is not None
    assert transport.params["start"] == 5
    assert page.next_cursor == "6"


def test_arxiv_full_text_resolver_uses_canonical_alias() -> None:
    work_id = uuid4()
    work = Work(work_id=work_id, title="Paper")
    identifier = WorkIdentifier(
        identifier_id=uuid4(),
        work_id=work_id,
        scheme="arxiv",
        value="arXiv:2401.01234v2",
    )

    resource = ArxivFullTextResolver().resolve(work, (identifier,), ())

    assert resource is not None
    assert resource.source_uri == "https://arxiv.org/pdf/2401.01234"
    assert resource.media_type == "application/pdf"
    assert resource.filename == "2401.01234.pdf"


def test_arxiv_identifier_normalization_supports_modern_and_legacy_forms() -> None:
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.01234v3") == "2401.01234"
    assert normalize_arxiv_id("http://arxiv.org/pdf/hep-ex/0307015v1.pdf") == "hep-ex/0307015"
