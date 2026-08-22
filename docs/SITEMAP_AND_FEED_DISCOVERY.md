# Sitemap and feed discovery

Issue #28 preserves URL-discovery provenance without turning discovery documents into research-domain identity.

`SitemapFeedDiscoverer` reads already-acquired XML and emits existing `ResourceLinkObservation` records for:

- sitemap `urlset` entries;
- sitemap-index child sitemaps;
- RSS 2.0 items;
- Atom entries and their links.

It advertises `Capability.SITEMAPS`, `Capability.FEEDS`, and `Capability.LINK_DISCOVERY` through a discovery adapter manifest.

## Native-first provenance

Each emitted link keeps the normalized discovery-document URI and a stable source ordinal. Format-specific metadata remains source-native where possible:

- sitemap `lastmod` text;
- RSS `guid`, title, and native `pubDate` text;
- an additional normalized RSS timestamp when parsing succeeds;
- Atom entry ID, title, `published`, `updated`, link `rel`, and media-type hint.

Targets use the same secret-safe `normalize_http_uri()` contract as HTTP observations and generic HTML link discovery. Relative feed links are resolved against the acquired feed URI. A malformed individual target is skipped without losing later valid entries; malformed XML itself fails closed because the document structure cannot be trusted.

## Boundary

This adapter does **not** perform HTTP requests, follow child sitemaps, poll feeds, recursively crawl entries, decide crawl eligibility, or create canonical `Work` records.

```text
acquired sitemap/feed artifact
    -> SourceObservation
    -> SitemapFeedDiscoverer
    -> ResourceLinkObservation[]
    -> later traversal policy / checkpointing
    -> optional acquisition
```

The later traversal layer must apply the existing acquisition/security budgets before fetching any emitted target.

## Run focused tests

```bash
uv run --no-sync pytest tests/test_sitemap_feed_discovery.py
```

If an expected entry is absent, first verify the XML root is one of `urlset`, `sitemapindex`, `rss`, or `feed`, then check whether the target resolves to a valid HTTP(S) URI. Source ordinals intentionally refer to the original discovery-document order, so skipped malformed entries do not renumber later observations.
