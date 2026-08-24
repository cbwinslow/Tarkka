# Milestone 3 — Scholarly Discovery, Identity, and Enrichment

## Status

**Complete for the local/offline research workflow.**

Tarkka can now discover scholarly works across multiple providers, preserve reproducible search
snapshots, explicitly promote selected results into canonical Works, enrich known identities,
acquire available full text, and surface ambiguous identities for review without silently merging
them.

## Provider policy

Discovery supports three provider modes:

- `auto` — choose the smallest useful provider set from provider-neutral research intent
- `only` — use exactly the explicitly selected provider or providers
- `all` — query every enabled provider and combine the results strictly

The current `auto` routing policy is intentionally deterministic and replaceable:

| Research intent | Preferred provider |
| --- | --- |
| `broad` | OpenAlex |
| `preprint` | arXiv |
| `citations` | Semantic Scholar |
| `bibliographic` | Crossref |

The CLI exposes the same provider-neutral intent contract:

```bash
tarkka discover "MLB win probability" --intent broad
tarkka discover "baseball forecasting" --intent preprint
tarkka discover "citation network baseball models" --intent citations
tarkka discover "DOI metadata baseball forecasting" --intent bibliographic
```

Explicit `--provider` selection remains authoritative and does not depend on intent routing.

## Delivered capabilities

### Discovery and snapshots

- provider-neutral `ResearchQuery`, `DiscoveryRecord`, `DiscoveryPage`, `DiscoveryResult`, and
  `SearchSnapshot` contracts
- OpenAlex, Crossref, Semantic Scholar, and arXiv adapters
- deterministic provider selection and result-budget allocation
- bounded concurrent multi-provider execution
- provider-keyed continuation cursors
- reproducible append-only local SearchSnapshots
- strict snapshot replay and corruption detection
- resilient HTTP retries, deadlines, `Retry-After`, and provider error aggregation

### Identity and Work persistence

- normalized DOI and arXiv strong identifiers
- Tarkka-owned canonical `work_id`
- typed identifier aliases with uniqueness protection
- preserved provider source observations
- explicit snapshot-result selection into a Work
- idempotent persistence and fail-closed strong-identity conflicts
- local JSON and PostgreSQL `WorkRepository` implementations validated against one shared contract
- explicit `TARKKA_WORK_BACKEND=postgres` selection for Work CLI persistence, while local JSON
  remains the default
- immutable Work creation timestamps across metadata evolution
- Crossref single-DOI enrichment
- explainable fuzzy identity candidates for records without sufficient strong identifiers
- explicit accept/reject identity review decisions with immutable matcher/evidence provenance
- **no fuzzy automatic merge**

### Full-text acquisition

- provider-neutral `FullTextResolver` and `BinaryFetcher` ports
- arXiv PDF resolution
- typed provider-observation full-text resolution, including Semantic Scholar `openAccessPdf`
- HTTPS-only, size-bounded, media-type-checked downloads
- immutable Artifact storage plus Acquisition provenance
- normalization through the existing parser pipeline

## End-to-end workflow

```text
research query
    ↓
provider intent / explicit provider policy
    ↓
discovery
    ↓
SearchSnapshot
    ↓
explicit result selection
    ↓
canonical Work
    ├── optional metadata enrichment
    ├── optional fuzzy identity review
    └── available full-text acquisition
             ↓
        Artifact / Acquisition
             ↓
        Document / Section / Passage
```

Representative CLI flow:

```bash
tarkka discover "machine learning MLB outcomes" --intent broad
tarkka work save --snapshot <snapshot-id> --index <result-index>
tarkka work show <work-id>
tarkka work enrich <work-id>
tarkka work acquire <work-id>

tarkka identity suggest --snapshot <snapshot-id>
tarkka identity decide \
  --snapshot <snapshot-id> \
  --left <left-index> \
  --right <right-index> \
  --decision accept
```

## Deferred by design

These are useful future extensions but are **not blockers** for structured research extraction:

1. automatic-vs-explicit enrichment policy based on measured metadata gain, latency, and failures
2. additional full-text resolvers when real workflows justify them
3. richer provider health/cost/credential-aware routing behind the existing `ProviderSelector`
4. reconciliation that consumes accepted fuzzy-identity decisions and explicitly merges canonical
   Works with full provenance and conflict checks

## Exit criteria

Milestone 3 is complete because Tarkka now has a reproducible path from scholarly search to
normalized documents while preserving provider independence, canonical identity, provenance, and
human-review boundaries.

The next milestone is **structured research extraction**: turning normalized passages into typed,
evidence-backed Claims, Methods, Hypotheses, Datasets, Variables, Models, Metrics, Results, and
Limitations.

## Invariant

Provider selection is policy. Canonical identity belongs to Tarkka, not to a provider. Fuzzy evidence
may recommend review but must never silently become canonical identity. Every acquired or enriched
observation must retain enough provenance to reconstruct where it came from.
