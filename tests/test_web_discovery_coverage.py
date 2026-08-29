from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

import tarkka.infrastructure.web.sitemap_feed_discovery as sitemap_module
from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.web.link_discovery import HtmlResourceLinkDiscoverer
from tarkka.infrastructure.web.sitemap_feed_discovery import SitemapFeedDiscoverer

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=uuid4(),
        source_name="web-discovery-fixture",
        basis=ObservationBasis.NATIVE,
    )


def test_html_discovery_validates_inputs_and_recovers_from_source_noise() -> None:
    discoverer = HtmlResourceLinkDiscoverer()
    observation = _observation()

    with pytest.raises(ValueError, match="SourceObservation"):
        discoverer.discover(cast(SourceObservation, object()), html="", base_uri="https://x.test")
    with pytest.raises(ValueError, match="HTML must be a string"):
        discoverer.discover(observation, html=cast(str, object()), base_uri="https://x.test")

    html = """
    <div href="/ignored">not a link element</div>
    <a>missing href</a>
    <area />
    <link />
    <a href="/first"> First <b>bold</b> label </a>
    <a href="/outer">Outer<a href="/inner">Inner</a>
    <link href="/canonical" rel="canonical" type="text/html" />
    <area href="/dataset" rel="dataset" />
    <a href="mailto:test@example.com">mail</a>
    <a href="http://[bad">bad</a>
    <a href="//other.example/path">Outbound</a>
    <a href="/unclosed">Unclosed
    """
    links = discoverer.discover(
        observation,
        html=html,
        base_uri="https://Example.Test/base/page",
    )

    by_uri = {link.target_uri: link for link in links}
    assert "https://example.test/first" in by_uri
    assert by_uri["https://example.test/first"].label == "First bold label"
    assert by_uri["https://example.test/canonical"].relation is ResourceRelation.CANONICAL
    assert by_uri["https://example.test/dataset"].relation is ResourceRelation.DATASET
    assert by_uri["https://other.example/path"].metadata["scope"] == "outbound"
    assert by_uri["https://example.test/unclosed"].label == "Unclosed"
    assert all(link.target_uri.startswith(("http://", "https://")) for link in links)


def test_html_nested_anchor_recovery_emits_outer_before_inner() -> None:
    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html='<a href="/outer">Outer<a href="/inner">Inner</a>',
        base_uri="https://example.test/",
    )
    assert [(link.target_uri, link.label) for link in links] == [
        ("https://example.test/outer", "Outer"),
        ("https://example.test/inner", "Inner"),
    ]


def test_sitemap_discovery_validates_inputs_size_depth_and_element_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discoverer = SitemapFeedDiscoverer()
    observation = _observation()

    with pytest.raises(ValueError, match="SourceObservation"):
        discoverer.discover(
            cast(SourceObservation, object()),
            xml="<urlset />",
            source_uri="https://example.test/sitemap.xml",
        )
    with pytest.raises(ValueError, match="XML must be a string"):
        discoverer.discover(
            observation,
            xml=cast(str, object()),
            source_uri="https://example.test/sitemap.xml",
        )

    monkeypatch.setattr(sitemap_module, "_MAX_XML_CHARS", 4)
    with pytest.raises(ValueError, match="parser size limit"):
        discoverer.discover(
            observation,
            xml="<urlset />",
            source_uri="https://example.test/sitemap.xml",
        )
    monkeypatch.setattr(sitemap_module, "_MAX_XML_CHARS", 5_000_000)

    monkeypatch.setattr(sitemap_module, "_MAX_XML_ELEMENTS", 1)
    with pytest.raises(ValueError, match="element limit"):
        discoverer.discover(
            observation,
            xml="<urlset><url /></urlset>",
            source_uri="https://example.test/sitemap.xml",
        )
    monkeypatch.setattr(sitemap_module, "_MAX_XML_ELEMENTS", 100_000)

    monkeypatch.setattr(sitemap_module, "_MAX_XML_DEPTH", 1)
    with pytest.raises(ValueError, match="nesting-depth limit"):
        discoverer.discover(
            observation,
            xml="<urlset><url /></urlset>",
            source_uri="https://example.test/sitemap.xml",
        )


def test_sitemap_discovery_rejects_malformed_and_unsupported_xml() -> None:
    discoverer = SitemapFeedDiscoverer()
    observation = _observation()

    with pytest.raises(ValueError, match="unable to parse"):
        discoverer.discover(
            observation,
            xml="<urlset>",
            source_uri="https://example.test/sitemap.xml",
        )
    with pytest.raises(ValueError, match="unsupported sitemap/feed root"):
        discoverer.discover(
            observation,
            xml="<unknown />",
            source_uri="https://example.test/source.xml",
        )


def test_urlset_and_sitemap_index_skip_missing_and_malformed_targets() -> None:
    discoverer = SitemapFeedDiscoverer()
    observation = _observation()

    urlset = """
    <urlset>
      <url><lastmod>2026-01-01</lastmod></url>
      <url><loc>http://[bad</loc></url>
      <url><loc>/paper</loc><lastmod>2026-02-03</lastmod></url>
    </urlset>
    """
    links = discoverer.discover(
        observation,
        xml=urlset,
        source_uri="https://example.test/sitemap.xml",
    )
    assert len(links) == 1
    assert links[0].target_uri == "https://example.test/paper"
    assert links[0].metadata["source_ordinal"] == 2
    assert links[0].metadata["last_modified"] == "2026-02-03"

    sitemap_index = """
    <sitemapindex>
      <sitemap><lastmod>2026-01-01</lastmod></sitemap>
      <sitemap><loc>/nested.xml</loc></sitemap>
    </sitemapindex>
    """
    links = discoverer.discover(
        observation,
        xml=sitemap_index,
        source_uri="https://example.test/root.xml",
    )
    assert len(links) == 1
    assert links[0].target_uri == "https://example.test/nested.xml"
    assert links[0].media_type == "application/xml"


def test_rss_feed_handles_missing_channel_links_and_invalid_dates() -> None:
    discoverer = SitemapFeedDiscoverer()
    observation = _observation()

    assert discoverer.discover(
        observation,
        xml="<rss />",
        source_uri="https://example.test/feed.xml",
    ) == ()

    rss = """
    <rss><channel>
      <item><title>Missing</title></item>
      <item>
        <title> Bad   date </title>
        <link>/article</link>
        <guid>entry-1</guid>
        <pubDate>definitely not a date</pubDate>
      </item>
      <item>
        <title>Good date</title>
        <link>https://other.example/article</link>
        <pubDate>Wed, 02 Oct 2002 13:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """
    links = discoverer.discover(
        observation,
        xml=rss,
        source_uri="https://example.test/feed.xml",
    )
    assert len(links) == 2
    assert links[0].label == "Bad date"
    assert links[0].metadata["published_at_normalized"] is None
    assert links[1].metadata["published_at_normalized"] == "2002-10-02T13:00:00+00:00"


def test_atom_feed_skips_empty_href_and_maps_all_relation_types() -> None:
    discoverer = SitemapFeedDiscoverer()
    observation = _observation()
    atom = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>entry-1</id><title>Entry</title>
        <published>2026-01-01T00:00:00Z</published><updated>2026-01-02T00:00:00Z</updated>
        <link />
        <link href="/default" />
        <link href="/canonical" rel="canonical" />
        <link href="/supplement" rel="supplementary" />
        <link href="/dataset" rel="dataset" />
        <link href="/software" rel="software" />
        <link href="/related" rel="other" type="application/test" />
      </entry>
    </feed>
    """
    links = discoverer.discover(
        observation,
        xml=atom,
        source_uri="https://example.test/feed.atom",
    )
    relations = {link.target_uri: link.relation for link in links}
    assert relations["https://example.test/default"] is ResourceRelation.ALTERNATE
    assert relations["https://example.test/canonical"] is ResourceRelation.CANONICAL
    assert relations["https://example.test/supplement"] is ResourceRelation.SUPPLEMENT
    assert relations["https://example.test/dataset"] is ResourceRelation.DATASET
    assert relations["https://example.test/software"] is ResourceRelation.SOFTWARE
    assert relations["https://example.test/related"] is ResourceRelation.RELATED
    assert next(
        link for link in links if link.target_uri == "https://example.test/related"
    ).media_type == "application/test"


def test_rss_without_pubdate_preserves_none_normalization() -> None:
    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml="<rss><channel><item><link>/x</link></item></channel></rss>",
        source_uri="https://example.test/feed.xml",
    )
    assert len(links) == 1
    assert links[0].metadata["published_at"] is None
    assert links[0].metadata["published_at_normalized"] is None
