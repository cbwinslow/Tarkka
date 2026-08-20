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

### arXiv

Available as a specialized discovery and full-text source. The adapter maps Atom results into the
same `DiscoveryRecord` contract, preserves abstracts/categories, normalizes arXiv identifiers to a
version-independent Work alias, and keeps observed version-specific entry/PDF metadata as provider
provenance.

arXiv is currently available through explicit provider selection and `all`; smarter `auto` routing is
a separate policy change.

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
        "arxiv": "0",
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

# Specialized preprint discovery
tarkka discover 'baseball "win probability"' --provider arxiv

# Explicit multi-provider search
tarkka discover "MLB betting models" --provider openalex --provider crossref

# Exhaustive fan-out
tarkka discover "baseball forecasting" --provider all

# Continue provider-specific pages
tarkka discover "baseball forecasting" --provider all \
  --cursor openalex='...' \
  --cursor crossref='...' \
  --cursor semantic-scholar='100' \
  --cursor arxiv='25'
```

The first response remains compact: snapshot ID, stable result index, title, year, provider identity,
DOI, citation count, and open-access URL. Abstracts, persisted Work state, enrichment, and full
records should be expanded or invoked only when useful.

A selected result is persisted explicitly and reproducibly:

```bash
tarkka work save --snapshot <snapshot-id> --index <result-index>
tarkka work show <work-id>
tarkka work enrich <work-id>
tarkka work acquire <work-id>
```

## Full-text acquisition

`FullTextResolver` and `BinaryFetcher` are provider-neutral ports. `work acquire` resolves one
representation, downloads it over bounded HTTPS, preserves the remote source URI in acquisition
provenance, stores the bytes as an immutable content-addressed Artifact, and then runs the existing
normalization pipeline.

In this milestone, the CLI configures **only `ArxivFullTextResolver`**. A Work therefore needs a valid
arXiv alias for `work acquire` to succeed today. DOI-only/Crossref/other-provider acquisition will be
added by registering additional resolver adapters; providers do not call one another.

Downloaded PDFs require the optional Docling parser because acquisition means acquire **and
normalize**, not download-only staging.

## Reliability

The shared stdlib HTTP transport has configurable per-attempt and total timeouts, retries transient
network failures and 429/5xx responses, honors numeric and HTTP-date `Retry-After`, and applies
jittered exponential backoff otherwise. Provider failures are isolated while concurrent calls settle
and are then reported together with useful exception context.

Full-text downloads are size-bounded, HTTPS-only (including the final redirect target), validate the
expected media type, reject unsafe filesystem names, clean partial files on failure, and run inside a
validated temporary acquisition directory.

## Search snapshots

Every discovery result receives a stable snapshot UUID. The local runtime appends the complete
compact result set, provider policy, filters, and provider-keyed continuation cursors to
`~/.tarkka/search_snapshots.jsonl`. Local appends are inter-process locked and durable for supported
local filesystems.

Snapshot reads acquire the same local inter-process lock as appends. Deserialization is strict:
malformed UUIDs, provider modes, typed identifier maps, cursor maps, or other persisted field types
fail with a dedicated snapshot-data error rather than being silently coerced.

The PostgreSQL reference schema includes `tarkka.search_snapshot`, targeted indexes, and append-only
protection against update/delete/truncate operations.

## Identity resolution

Discovery identity resolution is intentionally conservative:

1. validate and normalize DOI when available
2. normalize stable arXiv aliases when available
3. group matching normalized strong identifiers
4. otherwise preserve `(provider, provider_id)` as a distinct identity candidate

Do not automatically merge records by fuzzy title similarity. Ambiguous identity candidates should
later carry explicit confidence and evidence so they can be reviewed and regression-tested.

## Persistent canonical Work identity

Selected identity candidates can be persisted under a Tarkka-owned UUID:

```text
Canonical Work (work_id)
   ├── WorkIdentifier: doi -> 10.xxxx/...
   ├── WorkIdentifier: arxiv -> 2401.01234
   ├── WorkIdentifier: openalex -> W...
   ├── WorkIdentifier: semantic-scholar -> ...
   └── WorkSourceRecord[]
        ├── OpenAlex observation
        ├── Semantic Scholar observation
        ├── arXiv observation
        └── Crossref enrichment observation
```

Invariants:

- provider IDs never become Tarkka's primary key
- a normalized `(scheme, value)` identifier alias may belong to only one Work
- the same candidate may be persisted repeatedly without creating a second Work
- provider records remain distinct source observations
- identifiers discovered during enrichment are added as aliases
- conflicting strong identifiers fail closed instead of silently reassigning identity
- explicit snapshot selection promotes identity conflicts to a dedicated actionable error

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
explicit result selection
      ↓
identity candidate resolution
      ↓
persistent canonical Work
      ↓
selective enrichment
      ↓
full-text resolution / acquisition
      ↓
Artifact / Acquisition / Document normalization
```

Cross-provider combination, persistence, enrichment, acquisition policy, and identity resolution
belong in application services where policy, cost, retries, provenance, and conflicts can be
controlled explicitly.

## Delivered in this milestone so far

1. provider-neutral discovery contracts
2. pluggable `auto` plus explicit `only` / `all` policies
3. OpenAlex, Crossref, Semantic Scholar, and arXiv discovery adapters
4. concurrent multi-provider execution with deterministic result budgets
5. provider-keyed continuation cursors
6. DOI/arXiv validation, normalization, and conservative identity grouping
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
19. explicit snapshot-result selection into canonical Works
20. compact `work save`, `work show`, and `work enrich` CLI workflow
21. locked and strictly validated snapshot replay
22. actionable selected-result identity conflict errors
23. provider-neutral full-text resolver/fetcher contracts
24. arXiv PDF resolution and `work acquire`
25. remote acquisition provenance through the existing normalization pipeline

## Remaining Milestone 3 work

1. add richer query intent/capability routing
2. add explicit fuzzy identity candidates with confidence/evidence
3. decide/measure automatic versus explicit enrichment policy
4. add additional full-text resolvers when justified by measured workflows
5. add PostgreSQL Work repository implementation when the production persistence path is exercised

## Invariant

Provider selection is policy. Canonical Work identity belongs to Tarkka, not to a provider. Provider
adapters remain replaceable and must not call one another. Cross-provider combination, enrichment,
acquisition, and identity resolution belong in application services.
