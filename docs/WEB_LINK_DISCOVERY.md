# Generic web link discovery

Issue #28 distinguishes **site/resource discovery** from **document parsing** and from canonical research identity.

`HtmlResourceLinkDiscoverer` scans acquired HTML/XHTML for source-observed HTTP(S) links and emits existing `ResourceLinkObservation` records. It does not fetch those targets and does not create `Work` records.

## Preserved link facts

For `<a>`, `<area>`, and `<link>` elements the discoverer preserves:

- a secret-safe absolute target URI;
- source element type;
- source `rel` tokens;
- anchor text when available;
- source line/offset from the HTML parser;
- optional `type` media hint;
- a coarse exact-host scope classification (`internal` or `outbound`);
- a source-native relation when `rel` exposes canonical, alternate, supplement, dataset, or software semantics.

Unclassified HTTP(S) links remain `ResourceRelation.RELATED`. Multiple occurrences of the same target are kept as distinct source observations through deterministic occurrence IDs.

The target URI uses the same `normalize_http_uri()` retention contract as HTTP transport observations. URI userinfo is removed and common credential-bearing query values are redacted before persistence.

## Boundary with semantic document parsers

Native/semantic parsers such as JATS and `SemanticHtmlParser` preserve **document-semantic** resource relationships exposed by the publication format. Generic web link discovery instead preserves the wider page/site graph, including ordinary navigation and outbound links.

These layers are additive:

```text
acquired HTML artifact
    ├─ semantic parser -> Document + publication-native resource relations
    └─ link discoverer -> generic page/site ResourceLinkObservation records
```

Neither layer resolves a target into a canonical `Work`; identity resolution remains an application concern.

## Scope classification

`internal` currently means the normalized target hostname exactly equals the normalized base hostname. A subdomain is therefore `outbound`. This conservative rule avoids introducing a public-suffix/domain-ownership dependency into the low-level link extractor; a later crawl policy may define broader site scope explicitly.

## Run focused tests

```bash
uv run --no-sync pytest tests/test_web_link_discovery.py
```

If a link is absent, first verify that it resolves to HTTP or HTTPS. Malformed and non-network schemes such as `mailto:` are intentionally ignored so one bad page link does not poison discovery of the remaining page.
