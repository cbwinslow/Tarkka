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

`auto` is implemented through the replaceable `ProviderSelector` contract. The default selector
prefers OpenAlex for broad scholarly discovery, but future selectors can account for query intent,
credentials, rate limits, provider health, latency/cost budgets, or domain-specific coverage without
changing `DiscoveryService`.

## Provider roles

### OpenAlex

Primary broad-discovery source in the initial `auto` policy. It supplies scholarly work identities,
DOIs, citation counts, publication years, and open-access metadata.

### Crossref

Available as a search provider and intended to become especially important as a DOI metadata
enrichment source. Cursor pagination starts on every query so continuation is always available.

### Semantic Scholar

Available for relevance-ranked search plus citation, abstract, and open-access signals. Provider
responses without a stable `paperId` are rejected rather than assigned a fabricated identity.

## Pagination and result budgets

Provider cursors are opaque and provider-specific. Multi-provider continuation uses a map such as:

```python
ResearchQuery(
    text="baseball forecasting",
    mode=ProviderMode.ALL,
    limit=30,
    cursors={
        "openalex": "...",
        "crossref": "...",
        "semantic-scholar": "100",
    },
)
```

For multi-provider discovery, the global result budget is divided deterministically across selected
providers before requests are made. Tarkka therefore never fetches a provider page, discards unseen
records because of a later global truncation, and then advances past those records with its cursor.
The global limit must be at least the number of selected providers.

Independent provider requests execute concurrently. Output ordering remains deterministic.

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

# Continue provider-specific pages
tarkka discover "baseball forecasting" --provider all \
  --cursor openalex='...' \
  --cursor crossref='...' \
  --cursor semantic-scholar='100'
```

The first response remains compact: snapshot ID, title, year, provider identity, DOI, citation count,
and open-access URL. Abstracts and full records should be fetched only when requested.

## Reliability

The shared stdlib HTTP transport has configurable timeouts, retries transient network failures and
429/5xx responses, honors numeric `Retry-After`, and applies exponential backoff otherwise.
Provider failures are isolated while concurrent calls settle and are then reported together.

## Search snapshots

Every discovery result receives a stable snapshot UUID. The local runtime appends the complete
compact result set, provider policy, filters, and provider-keyed continuation cursors to
`~/.tarkka/search_snapshots.jsonl`. Local appends are inter-process locked and written as one JSONL
row.

The PostgreSQL reference schema includes `tarkka.search_snapshot`, indexes the main JSON/array query
surfaces, and enforces append-only behavior against update, delete, and truncate operations.

## Identity resolution

The first identity rule is intentionally conservative:

1. validate and normalize DOI when available
2. group matching normalized DOIs
3. otherwise preserve `(provider, provider_id)` as a distinct identity

Records without a stable provider identity are rejected rather than assigned a shared placeholder.
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
2. pluggable `auto` plus explicit `only` / `all` policies
3. OpenAlex, Crossref, and Semantic Scholar adapters
4. concurrent multi-provider execution with deterministic result budgets
5. provider-keyed continuation cursors
6. DOI validation, deduplication, and canonical identity grouping
7. resilient shared HTTP transport
8. reproducible, append-only local SearchSnapshots
9. append-only PostgreSQL SearchSnapshot migration and indexes
10. agent-friendly `tarkka discover` CLI
11. hardened GitHub Actions workflows
12. network-free adapter, orchestration, identity, CLI, and retry tests

## Remaining Milestone 3 work

1. implement Crossref enrichment by DOI
2. add canonical external-ID aliases to persistent `Work` entities
3. add richer query intent/capability routing
4. add arXiv as a specialized provider without changing the core contract
5. add explicit fuzzy identity candidates with confidence/evidence

## Invariant

Provider selection is a policy. Provider adapters remain replaceable and must not call one another.
Cross-provider combination, enrichment, and identity resolution belong in application services.
