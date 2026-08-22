from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.web.sitemap_feed_discovery import SitemapFeedDiscoverer

_OBSERVATION_ID = UUID("00000000-0000-0000-0000-000000000333")


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=_OBSERVATION_ID,
        source_name="http",
        basis=ObservationBasis.NATIVE,
        provider_record_id="https://example.org/sitemap.xml",
        media_type="application/xml",
    )


def test_sitemap_urlset_preserves_origin_and_last_modified() -> None:
    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.org/articles/one</loc>
        <lastmod>2026-08-20</lastmod>
      </url>
      <url><loc>https://example.org/articles/two?token=secret</loc></url>
    </urlset>
    """

    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/sitemap.xml",
    )

    assert [item.target_uri for item in links] == [
        "https://example.org/articles/one",
        "https://example.org/articles/two?token=%5BREDACTED%5D",
    ]
    assert links[0].metadata["discovery_kind"] == "sitemap_url"
    assert links[0].metadata["source_uri"] == "https://example.org/sitemap.xml"
    assert links[0].metadata["last_modified"] == "2026-08-20"
    assert links[0].metadata["source_ordinal"] == 0


def test_missing_sitemap_target_does_not_renumber_later_source_occurrence() -> None:
    xml = """
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><lastmod>2026-08-19</lastmod></url>
      <url><loc>https://example.org/articles/two</loc></url>
    </urlset>
    """

    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/sitemap.xml",
    )

    assert len(links) == 1
    assert links[0].metadata["source_ordinal"] == 1


def test_sitemap_index_preserves_child_sitemap_provenance() -> None:
    xml = """
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap>
        <loc>https://example.org/sitemap-articles.xml</loc>
        <lastmod>2026-08-21T10:00:00Z</lastmod>
      </sitemap>
    </sitemapindex>
    """

    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/sitemap.xml",
    )

    assert len(links) == 1
    assert links[0].target_uri == "https://example.org/sitemap-articles.xml"
    assert links[0].media_type == "application/xml"
    assert links[0].metadata["discovery_kind"] == "sitemap_index"
    assert links[0].metadata["last_modified"] == "2026-08-21T10:00:00Z"


def test_rss_feed_preserves_native_and_normalized_publication_time() -> None:
    xml = """
    <rss version="2.0"><channel>
      <title>Research updates</title>
      <item>
        <guid>paper-1</guid>
        <title>Paper One</title>
        <link>https://example.org/papers/one</link>
        <pubDate>Fri, 21 Aug 2026 15:30:00 GMT</pubDate>
      </item>
    </channel></rss>
    """

    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/feed.xml",
    )

    assert len(links) == 1
    assert links[0].label == "Paper One"
    assert links[0].relation is ResourceRelation.RELATED
    assert links[0].metadata["entry_id"] == "paper-1"
    assert links[0].metadata["published_at"] == "Fri, 21 Aug 2026 15:30:00 GMT"
    assert links[0].metadata["published_at_normalized"] == "2026-08-21T15:30:00+00:00"
    assert links[0].metadata["discovery_kind"] == "rss_item"


def test_atom_feed_preserves_entry_links_timestamps_and_relative_targets() -> None:
    xml = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Research feed</title>
      <entry>
        <id>urn:paper:2</id>
        <title>Paper Two</title>
        <published>2026-08-20T12:00:00Z</published>
        <updated>2026-08-21T12:00:00Z</updated>
        <link rel="alternate" type="text/html" href="papers/two" />
        <link rel="enclosure" type="application/pdf" href="/papers/two.pdf" />
      </entry>
    </feed>
    """

    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/feeds/atom.xml",
    )

    assert [item.target_uri for item in links] == [
        "https://example.org/feeds/papers/two",
        "https://example.org/papers/two.pdf",
    ]
    assert links[0].relation is ResourceRelation.ALTERNATE
    assert links[0].media_type == "text/html"
    assert links[1].relation is ResourceRelation.RELATED
    assert links[1].media_type == "application/pdf"
    assert links[0].metadata["entry_id"] == "urn:paper:2"
    assert links[0].metadata["published_at"] == "2026-08-20T12:00:00Z"
    assert links[0].metadata["updated_at"] == "2026-08-21T12:00:00Z"


def test_atom_relations_preserve_supported_resource_semantics_and_ordinals() -> None:
    xml = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Artifacts</title>
        <link rel="dataset" />
        <link rel="dataset" href="/data.csv" />
        <link rel="software" href="/code" />
        <link rel="supplement" href="/supp.pdf" />
      </entry>
    </feed>
    """

    links = SitemapFeedDiscoverer().discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/feed.xml",
    )

    assert [item.relation for item in links] == [
        ResourceRelation.DATASET,
        ResourceRelation.SOFTWARE,
        ResourceRelation.SUPPLEMENT,
    ]
    assert [item.metadata["source_ordinal"] for item in links] == [1, 2, 3]


def test_discovery_is_deterministic_and_malformed_targets_are_isolated() -> None:
    xml = """
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>http://[::1</loc></url>
      <url><loc>https://example.org/good</loc></url>
    </urlset>
    """
    discoverer = SitemapFeedDiscoverer()

    first = discoverer.discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/sitemap.xml",
    )
    second = discoverer.discover(
        _observation(),
        xml=xml,
        source_uri="https://example.org/sitemap.xml",
    )

    assert first == second
    assert len(first) == 1
    assert first[0].target_uri == "https://example.org/good"
    assert first[0].metadata["source_ordinal"] == 1


def test_xml_parser_enforces_size_and_depth_bounds() -> None:
    discoverer = SitemapFeedDiscoverer()
    with pytest.raises(ValueError, match="size limit"):
        discoverer.discover(
            _observation(),
            xml="<urlset>" + ("x" * 5_000_001) + "</urlset>",
            source_uri="https://example.org/sitemap.xml",
        )

    deeply_nested = "<urlset>" + ("<x>" * 64) + ("</x>" * 64) + "</urlset>"
    with pytest.raises(ValueError, match="nesting-depth limit"):
        discoverer.discover(
            _observation(),
            xml=deeply_nested,
            source_uri="https://example.org/sitemap.xml",
        )


def test_invalid_xml_unknown_roots_and_boundaries_fail_closed() -> None:
    discoverer = SitemapFeedDiscoverer()
    with pytest.raises(ValueError, match="parse sitemap/feed XML"):
        discoverer.discover(
            _observation(),
            xml="<urlset>",
            source_uri="https://example.org/sitemap.xml",
        )
    with pytest.raises(ValueError, match="unsupported sitemap/feed root"):
        discoverer.discover(
            _observation(),
            xml="<document />",
            source_uri="https://example.org/document.xml",
        )
    with pytest.raises(ValueError, match="absolute HTTP"):
        discoverer.discover(
            _observation(),
            xml="<urlset />",
            source_uri="/relative.xml",
        )
    with pytest.raises(ValueError, match="XML must be a string"):
        discoverer.discover(
            _observation(),
            xml=b"<urlset />",  # type: ignore[arg-type]
            source_uri="https://example.org/sitemap.xml",
        )
