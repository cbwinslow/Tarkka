# Milestone 3 — Scholarly Discovery and Provider Selection

## Goal

Add provider-neutral scholarly discovery without forcing every research query through every external
source. Tarkka should be able to search narrowly by default, fan out when explicitly requested, and
later enrich selected candidates from secondary metadata providers.

## Provider policy

Discovery requests use one of three modes:

- `auto` — choose the smallest useful provider set for the request
- `only` — use exactly the named provider or providers
- `all` — query every enabled provider and deduplicate the combined result set

The current `auto` policy prefers OpenAlex for broad scholarly discovery. This is intentionally a
policy decision in the application layer, not a hard-coded property of the provider adapters.

Future policies may consider:

- query intent
- desired citation/semantic features
- open-access requirements
- API credentials and rate limits
- provider health
- latency/cost budgets
- domain-specific coverage
- whether a DOI or another strong external identifier is already known

## Provider roles

### OpenAlex

Primary broad-discovery source in the initial `auto` policy. It supplies scholarly work identities,
DOIs, citation counts, publication years, and open-access metadata.

### Crossref

Available as a search provider, but expected to become especially important as a DOI metadata
enrichment source. Tarkka should not require a Crossref search for every broad discovery request.

### Semantic Scholar

Available for relevance-ranked search plus citation, abstract, and open-access signals. It can be
selected explicitly or included in `all`; future `auto` policies can invoke it when semantic/citation
features are requested.

## Canonical request

```python
ResearchQuery(
    text="machine learning MLB game outcome prediction",
    mode=ProviderMode.AUTO,
    limit=25,
)
```

All providers implement the same `DiscoveryProvider.search()` port and return `DiscoveryPage`.
Provider-specific pagination state is represented as an opaque string cursor at the Tarkka boundary,
even when the upstream API uses an integer offset.

## CLI

```bash
# Narrow default policy
tarkka discover "machine learning MLB game outcome prediction"

# Explicit provider
tarkka discover "MLB win probability" --provider semantic-scholar

# Explicit multi-provider search
tarkka discover "MLB betting models" --provider openalex --provider crossref

# Exhaustive fan-out
tarkka discover "baseball forecasting" --provider all
```

The first response remains compact: title, year, provider identity, DOI, citation count, and open
access URL. Abstracts and full records should be fetched only when requested.

## Deduplication

The first deduplication rule is intentionally conservative:

1. normalized DOI when available
2. otherwise `(provider, provider_id)`

Do not merge records by fuzzy title similarity yet. That belongs in the canonical identity resolver,
where ambiguous merges can be scored, explained, and tested.

## Next steps within Milestone 3

1. persist reproducible `SearchSnapshot` records
2. add canonical external-ID aliases to `Work`
3. implement DOI-first identity resolution
4. implement Crossref enrichment by DOI
5. add provider retry/rate-limit/backoff policy
6. add per-provider continuation commands
7. add richer query intent/capability routing
8. add arXiv as a specialized provider without changing the core contract

## Invariant

Provider selection is a policy. Provider adapters remain replaceable and must not call one another.
Cross-provider combination, enrichment, and identity resolution belong in application services.
