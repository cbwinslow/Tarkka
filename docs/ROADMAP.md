# Roadmap

## Strategy

Build the smallest coherent vertical slice first, then expand through adapters and domain packs. Avoid implementing every possible source, model provider, or enterprise feature before the core contracts are measured and validated.

Milestone numbers in implementation PRs map to the phases below; the phase names are the authoritative long-term sequence.

## Current status

- Phase 0 — Foundation: **complete**
- Phase 1 — Core local vertical slice: **substantially complete**
- Phase 2 — Scholarly discovery and identity: **complete for the local/offline workflow**
- Phase 3 — Structured research extraction: **substantially complete for the initial local workflow;
  source/document intelligence expands incrementally through additional adapters**

The merged implementation includes the typed core, content-addressed local artifacts, normalized documents, optional Docling parsing, acquisition provenance, provider-neutral scholarly discovery, capability-aware routing, reproducible SearchSnapshots, canonical Work identity, selective enrichment, full-text acquisition, review-only fuzzy identity candidates, generalized evidence locators, first-class Figure/Table/Equation source artifacts, evidence-backed claim extraction, the full first-pass research object vocabulary, model-assisted extraction, evaluation fixtures, bounded model requests, and contract-tested local/PostgreSQL Work persistence.

The initial source/document intelligence sequence is delivered. Future JATS, EPUB, HTML, PDF,
crawler, citation, supplement, and provider integrations must extend these preservation boundaries
rather than forcing rewrites. The next product capability is evidence verification that distinguishes
citation from actual support.

## Phase 0 — Foundation

Status: **complete**

Delivered:

- project charter
- architecture
- canonical data model
- pipeline stages
- plugin contracts
- agent interface
- context-efficiency design
- security/rights baseline
- Tarkka naming decision and lowercase machine namespace
- contribution/development guidance
- shared `AGENTS.md` and Claude-specific context guidance
- first portable research-discovery skill

## Phase 1 — Core local vertical slice

Status: **substantially complete**

Goal: ingest local research and retrieve normalized content on one machine without requiring an LLM, cloud service, or database server.

Delivered:

- Python package skeleton and typed domain models
- local SHA-256 content-addressed artifact store
- separate acquisition provenance
- lightweight local metadata repository
- PostgreSQL reference schema/migrations
- PostgreSQL `WorkRepository` adapter with real-service contract validation
- plain-text/Markdown parser
- optional Docling rich-document adapter
- canonical `Artifact -> Document -> Section -> Passage` normalization
- generalized Figure/Table/Equation document source artifacts
- progressive resource manifests
- `tarkka ingest`, `tarkka inspect`, and `tarkka read`
- parser contract/integration tests
- Ruff, strict mypy, pytest, and Docling CI

Remaining Phase 1 work can proceed only when required by downstream features:

- PostgreSQL repositories for the remaining canonical model beyond Work identity
- structured logging/observability hooks
- PostgreSQL full-text + pgvector retrieval
- deterministic chunk/index pipeline beyond the current passage model

## Phase 2 — Scholarly discovery and identity

Status: **complete for the local/offline workflow**

Goal: build reproducible research collections from topics rather than manual files only.

Delivered:

- provider-neutral discovery contracts
- replaceable capability-aware `ProviderSelector`
- `auto`, explicit-provider, and `all` modes
- `broad`, `preprint`, `citations`, and `bibliographic` research intents
- OpenAlex, Crossref, Semantic Scholar, and arXiv discovery adapters
- bounded concurrent fan-out and provider-specific continuation cursors
- resilient HTTP retries/rate-limit handling
- reproducible SearchSnapshots
- DOI/arXiv normalization and deterministic strong-ID identity
- persistent canonical Work identity with aliases and provider observations
- local JSON and PostgreSQL Work repositories validated against the same persistence contract
- explicit `TARKKA_WORK_BACKEND=postgres` runtime selection for Work CLI persistence; JSON remains
  the dependency-free default
- Crossref DOI enrichment
- generic full-text acquisition with arXiv and typed provider representations
- explicit fuzzy identity candidates with auditable accept/reject decisions
- `tarkka discover`, `work save/show/enrich/acquire`, and `identity suggest/decide`

Deferred by design until measured workflows justify them:

- automatic enrichment policy
- additional full-text resolvers
- provider-health/cost-aware routing
- accepted-candidate reconciliation/merge workflow

Exit criteria are met for the local/offline profile: discovery is replayable, selected works have Tarkka-owned identity, provider observations remain separate, enrichment does not couple providers, and ambiguous identity is represented explicitly rather than silently collapsed.

## Phase 3 — Structured research extraction and source intelligence

Status: **substantially complete for the initial local workflow**

Goal: turn research sources into reusable, evidence-grounded research objects without losing native document/provider structure.

### Delivered extraction foundation

- generalized Evidence contract with passage, figure, table-cell, and equation locators
- immutable extraction-run metadata separated from record-level confidence/review provenance
- human review state
- author-stated vs inferred attribution
- typed Claim, Hypothesis, Method, Dataset, Variable, Model, Metric, Result, and Limitation contracts
- provider/model-neutral structured extraction ports and postcondition validation
- `ExtractionRepository` persistence port with run-scoped reads and atomic/idempotent write semantics
- PostgreSQL reference schema with lineage/evidence validation
- deterministic claim extraction
- local JSON extraction repository
- claim/evidence CLI inspection
- provider-neutral structured model boundary
- OpenAI-compatible claim and research adapters
- extraction evaluation fixtures and claim precision/recall metrics
- bounded model requests with request-local evidence validation and semantic overlap deduplication
- property-based batching tests and explicit testing taxonomy

### Source/document intelligence — delivered core sequence

The governing rule is:

> **Preserve native structure first; normalize second; infer last.**

See [`SOURCE_DOCUMENT_PRESERVATION.md`](SOURCE_DOCUMENT_PRESERVATION.md).

1. **#25 — preservation/capability contracts**
   - generic immutable SourceObservation
   - native/reconstructed/inferred distinction
   - capability manifests for providers/parsers/crawlers/enrichers
   - generic ResourceLinkObservation
   - additive migration path from existing source-record/full-text contracts
2. **#26 — bibliography/citation model**
   - BibliographicReference
   - CitationMention / CitationContext
   - resolved citation identity
   - provenance-backed WorkRelation
   - bounded cited/citing traversal policy
   - delivered: exact-identifier resolution CLI that creates `CITES` relations only with an
     explicit or uniquely linked citing Work
3. **#27 — native document structure adapters**
   - JATS XML first-class structure
   - Docling/PDF native/reconstructed figures/tables/equations/layout
   - EPUB and semantic HTML
   - LaTeX/source bundles where practical
   - deterministic format-preservation fixture corpus
4. **#28 — bounded web/resource discovery**
   - HTTP/source observations
   - sitemap/feed/link discovery
   - resource/media routing
   - resumable bounded crawl policy
   - no research semantics embedded in crawler code
5. **Research packages / supplements**
   - link article representations, supplements, datasets, and software/code
   - delivered: bounded, provenance-preserving inspection from a Document/Artifact through
     its native observations; acquisition and identity resolution remain separate
   - prefer source-linked raw data over chart pixel reconstruction where available
6. **Optional OCR/vision/chart reconstruction**
   - remain replaceable reconstructed/inferred adapters
   - never overwrite immutable source-native observations

### Source/provider audit workstream

Before adding or upgrading a connector, inventory the upstream source's:

- stable identifiers
- native metadata
- references/citations
- full-text/alternate/supplement/dataset/software links
- author/organization/funder/award/license data
- versions/corrections/retractions
- pagination/rate/update behavior
- rights/access constraints
- source-native vs provider-inferred fields

Representative native payloads should become deterministic preservation fixtures.

Likely future source additions after the contracts are exercised include DataCite, PubMed/PubMed Central, ORCID/ROR enrichment, Zenodo/OSF/Figshare, and institutional repositories. Add them based on concrete workflows rather than source-count goals.

### Multimodal truth layers

```text
native Figure/Table/Equation or source artifact
    -> reconstructed observation (only when necessary)
    -> optional interpretation
    -> Result / Claim / other research object
```

OCR, vision, chart digitization, and embeddings are optional adapters. They are not requirements of the core document or evidence model.

Agents must return evidence-backed records and only concise visible reasoning summaries where useful. Hidden chain-of-thought is never persisted.

## Phase 4 — Evidence verification

Goal: distinguish citation from actual support.

Deliverables:

- claim/evidence relationships
- citation-context-aware verification workflow
- support/contradiction/qualification labels
- confidence and review state
- source passage/figure/table expansion
- cited-source traversal where bounded and permitted
- deterministic evaluation fixtures

Delivered foundation:

- immutable, verifier-versioned Claim-to-Evidence relations
- support/contradiction/qualification and related labels, including explicit no-evidence state
- confidence, human-review state, concise reasoning summary, and optional citation-context anchor
- bounded local CLI recording and progressive evidence/context expansion
- deterministic exact-handle evaluation metrics for verification labels

## Phase 5 — Agent-first serving

Goal: make Claude, Codex, and custom agents efficient research consumers.

Deliverables:

- MCP server
- compact capability discovery
- manifest/summary/evidence/full expansion ladder
- context-package service
- stable handles/saved result collections
- additional portable Agent Skills
- token/cost telemetry

Benchmarks:

- context tokens per task
- evidence recall/precision
- answer faithfulness
- number of expansion operations
- latency/cost

## Phase 6 — Reproducible outputs

Goal: convert research state into durable publications.

Deliverables:

- Quarto exporter
- bibliography generation
- evidence-linked reports
- research snapshot manifests
- JSON/JSONL and BibTeX/RIS/CSL-JSON export

## Phase 7 — First domain pack: Baseball

Goal: prove integration into MLB research/modeling without contaminating the generic core.

Deliverables:

- baseball ontology/vocabulary
- SABR/MLB/Statcast-oriented source catalog where permitted
- baseball research extraction rules
- ML-method extraction
- leakage/evidence-quality policy
- paper-to-feature candidate mapping
- paper-to-experiment handoff
- integration example with the MLB research/model registry

## Phase 8 — Second domain pack: Finance/Economics

Goal: prove the core is genuinely domain-agnostic.

Deliverables:

- finance/economics vocabulary
- academic/economic source catalog
- factor/model/variable extraction
- lookahead/survivorship-bias and transaction-cost observations
- FRED/SEC/NBER/CFA-style adapters or user-provided-content workflows where rights permit

## Phase 9 — Team/institutional scaling

Only after core workflows are measured and useful.

Potential deliverables:

- organization/workspace tenancy
- OIDC/SSO
- RBAC/ABAC
- object-store backend
- durable task queue
- worker pools
- quotas
- backups
- audit retention
- secrets integration
- deployment charts/manifests
- observability dashboards

## Phase 10 — Ecosystem

- plugin SDK
- domain-pack SDK
- provider registry/catalog
- templates
- benchmark suite
- public examples
- extension documentation

## Cross-cutting workstreams

### Testing and quality

Testing is continuous and is defined in [`TESTING.md`](TESTING.md). The suite grows through unit, contract, integration, regression, property-based, and opt-in external tests.

Every meaningful bug should gain a focused regression test. Bugs that expose a broader class of failures should also gain a contract or property-based invariant test.

The default CI profile remains network-free and credential-free. External database/model/provider tests are isolated and opt-in.

Coverage is measured with branch coverage as a diagnostic. Repository-wide thresholds are deferred until a stable baseline is known; critical contracts should be covered behaviorally rather than optimized for a vanity percentage.

For provider/document adapters, tests should verify preservation of source-native fields/structure rather than only successful parsing.

### Evaluation

Measure parser preservation quality, identity precision/recall, extraction accuracy, evidence verification, citation resolution quality, retrieval quality, context/token efficiency, latency, and cost.

### Documentation

Every public feature requires user workflow documentation, interface behavior, failure behavior, reproducibility notes, and agent-consumption guidance where applicable.

### Security and rights

Advance controls with deployment scope. Do not advertise institutional readiness before threat modeling, tenancy controls, artifact hardening, and rights-policy enforcement are implemented and tested.
