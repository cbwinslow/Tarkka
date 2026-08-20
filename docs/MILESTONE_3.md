# Milestone 3 — Scholarly Discovery, Identity, and Enrichment

## Goal

Add provider-neutral scholarly discovery without forcing every research query through every external
source. Tarkka should search narrowly by default, fan out when explicitly requested, preserve the
exact result set for reproducibility, persist selected works under an internal canonical identity,
and enrich those works only after identity resolution.

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

Available as a search provider and as a DOI metadata enricher. Discovery cursor pagination starts on
every search query so continuation is available. Enrichment uses the single-work DOI lookup endpoint
and produces another provider observation rather than making Crossref the canonical identity owner.

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
and open-access URL. Abstracts, persisted Work state, enrichment, and full records should be expanded
or invoked only when useful.

## Reliability

The shared stdlib HTTP transport has configurable per-attempt and total timeouts, retries transient
network failures and 429/5xx responses, honors numeric and HTTP-date `Retry-After`, and applies
jittered exponential backoff otherwise. Provider failures are isolated while concurrent calls settle
and are then reported together with useful exception context.

## Search snapshots

Every discovery result receives a stable snapshot UUID. The local runtime appends the complete
compact result set, provider policy, filters, and provider-keyed continuation cursors to
`~/.tarkka/search_snapshots.jsonl`. Local appends are inter-process locked and durable for supported
local filesystems.

The PostgreSQL reference schema includes `tarkka.search_snapshot`, targeted indexes, and append-only
protection against update/delete/truncate operations.

## Identity resolution

Discovery identity resolution is intentionally conservative:

1. validate and normalize DOI when available
2. group matching normalized DOIs
3. otherwise preserve `(provider, provider_id)` as a distinct identity candidate

Do not automatically merge records by fuzzy title similarity. Ambiguous identity candidates should
later carry explicit confidence and evidence so they can be reviewed and regression-tested.

## Persistent canonical Work identity

Selected identity candidates can be persisted under a Tarkka-owned UUID:

```text
Canonical Work (work_id)
   ├── WorkIdentifier: doi -> 10.xxxx/...
   ├── WorkIdentifier: openalex -> W...
   ├── WorkIdentifier: semantic-scholar -> ...
   └── WorkSourceRecord[]
        ├── OpenAlex observation
        ├── Semantic Scholar observation
        └── Crossref enrichment observation
```

Invariants:

- provider IDs never become Tarkka's primary key
- a normalized `(scheme, value)` identifier alias may belong to only one Work
- the same candidate may be persisted repeatedly without creating a second Work
- provider records remain distinct source observations
- identifiers discovered during enrichment are added as aliases
- conflicting strong identifiers fail closed instead of silently reassigning identity

The local/offline profile uses a durable JSON Work repository; PostgreSQL has dedicated `work`,
`work_identifier`, and `work_source_record` tables for the reference production model.

## Enrichment policy

Enrichment is a separate application stage from discovery. `WorkMetadataEnricher` adapters fetch a
provider observation for a known identity. The initial Crossref enrichment path looks up one work by
DOI.

Enrichment is conservative:

- the returned DOI must equal the requested normalized DOI
- already-selected canonical title/year values are not overwritten
- missing abstract, venue, publication type, and identifiers may be filled
- the complete provider observation remains available independently of the canonical projection

Future enrichment policy may decide whether to call Crossref automatically, selectively, or only on
explicit request. Provider adapters still must not call one another.

## Separation of stages

```text
provider selection
      ↓
discovery
      ↓
SearchSnapshot
      ↓
identity candidate resolution
      ↓
persistent canonical Work
      ↓
selective enrichment
      ↓
acquisition / normalization
```

Cross-provider combination, persistence, enrichment, and identity resolution belong in application
services where policy, cost, retries, provenance, and conflicts can be controlled explicitly.

## Delivered in this milestone so far

1. provider-neutral discovery contracts
2. pluggable `auto` plus explicit `only` / `all` policies
3. OpenAlex, Crossref, and Semantic Scholar discovery adapters
4. concurrent multi-provider execution with deterministic result budgets
5. provider-keyed continuation cursors
6. DOI validation, deduplication, and conservative identity grouping
7. resilient shared HTTP transport
8. reproducible, append-only local SearchSnapshots
9. append-only PostgreSQL SearchSnapshot migration
10. agent-friendly `tarkka discover` CLI
11. hardened GitHub Actions workflows
12. network-free adapter/orchestration/identity/retry tests
13. persistent canonical `Work` identity
14. typed external-ID aliases with uniqueness protection
15. preserved provider source observations
16. durable local Work repository and PostgreSQL Work identity schema
17. Crossref single-DOI metadata enrichment
18. idempotence/conflict/non-destructive enrichment tests

## Remaining Milestone 3 work

1. expose selected Work persistence/enrichment through a small user/agent-facing workflow
2. add richer query intent/capability routing
3. add arXiv as a specialized provider without changing the core contract
4. add explicit fuzzy identity candidates with confidence/evidence
5. decide/measure automatic versus explicit enrichment policy
6. add PostgreSQL Work repository implementation when the production persistence path is exercised

## Invariant

Provider selection is policy. Canonical Work identity belongs to Tarkka, not to a provider. Provider
adapters remain replaceable and must not call one another. Cross-provider combination, enrichment,
and identity resolution belong in application services.
