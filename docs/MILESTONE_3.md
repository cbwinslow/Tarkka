# Milestone 3 — Scholarly Discovery and Provider Selection

## Goal

Add provider-neutral scholarly discovery without forcing every research query through every external
source. Tarkka should search narrowly by default, fan out when explicitly requested, preserve the
exact result set for reproducibility, and enrich selected candidates only after identity resolution.

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

The first response remains compact: snapshot ID, title, year, provider identity, DOI, citation count,
and open-access URL. Abstracts and full records should be fetched only when requested.

## Search snapshots

Every discovery result receives a stable snapshot UUID. The local runtime appends the complete
compact result set, provider policy, filters, and continuation cursors to
`~/.tarkka/search_snapshots.jsonl`.

The PostgreSQL reference schema includes `tarkka.search_snapshot` for the production persistence
path. This makes later analysis auditable even when provider rankings or metadata change.

## Identity resolution

The first identity rule is intentionally conservative:

1. normalize and group matching DOIs
2. otherwise preserve `(provider, provider_id)` as a distinct identity

`CanonicalIdentityResolver` keeps all source records attached to the candidate and chooses a compact
preferred representation without discarding provenance.

Do not automatically merge records by fuzzy title similarity. Ambiguous identity candidates should
later carry explicit confidence and evidence so they can be reviewed and regression-tested.

## Separation of stages

```text
provider selection
      ↓
discovery
      ↓
search snapshot
      ↓
identity resolution
      ↓
enrichment
      ↓
acquisition / normalization
```

Provider adapters must not call one another. Cross-provider combination and enrichment belong in
application services where policy, cost, retries, and provenance can be controlled explicitly.

## Delivered in this slice

1. provider-neutral discovery contracts
2. `auto` / `only` / `all` selection policy
3. OpenAlex adapter
4. Crossref adapter
5. Semantic Scholar adapter
6. DOI-first deduplication and canonical identity grouping
7. reproducible local SearchSnapshots
8. PostgreSQL SearchSnapshot migration
9. agent-friendly `tarkka discover` CLI
10. network-free adapter and orchestration tests

## Remaining Milestone 3 work

1. implement Crossref enrichment by DOI
2. add canonical external-ID aliases to persistent `Work` entities
3. add provider retry/rate-limit/backoff policy
4. add per-provider continuation commands
5. add richer query intent/capability routing
6. add arXiv as a specialized provider without changing the core contract
7. add explicit fuzzy identity candidates with confidence/evidence

## Invariant

Provider selection is a policy. Provider adapters remain replaceable and must not call one another.
Cross-provider combination, enrichment, and identity resolution belong in application services.
