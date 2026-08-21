# Roadmap

## Strategy

Build the smallest coherent vertical slice first, then expand through adapters and domain packs. Avoid implementing every possible source, model provider, or enterprise feature before the core contracts are measured and validated.

Milestone numbers in implementation PRs map to the phases below; the phase names are the authoritative long-term sequence.

## Current status

- Phase 0 — Foundation: **complete**
- Phase 1 — Core local vertical slice: **substantially complete**
- Phase 2 — Scholarly discovery and identity: **complete for the local/offline workflow**
- Phase 3 — Structured research extraction: **in progress**

The merged implementation includes the typed core, content-addressed local artifacts, normalized documents, optional Docling parsing, acquisition provenance, provider-neutral scholarly discovery, capability-aware routing, reproducible SearchSnapshots, canonical Work identity, selective enrichment, full-text acquisition, review-only fuzzy identity candidates, evidence-backed claim extraction, model-assisted extraction, evaluation fixtures, and bounded model requests.

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
- plain-text/Markdown parser
- optional Docling rich-document adapter
- canonical `Artifact -> Document -> Section -> Passage` normalization
- progressive resource manifests
- `tarkka ingest`, `tarkka inspect`, and `tarkka read`
- parser contract/integration tests
- Ruff, strict mypy, pytest, and Docling CI

Remaining Phase 1 work can proceed only when required by downstream features:

- PostgreSQL repositories for the full canonical model
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
- Crossref DOI enrichment
- generic full-text acquisition with arXiv and typed provider representations
- explicit fuzzy identity candidates with auditable accept/reject decisions
- `tarkka discover`, `work save/show/enrich/acquire`, and `identity suggest/decide`

Deferred by design until measured workflows justify them:

- automatic enrichment policy
- additional full-text resolvers
- PostgreSQL Work repository implementation
- provider-health/cost-aware routing
- accepted-candidate reconciliation/merge workflow

Exit criteria are met for the local/offline profile: discovery is replayable, selected works have Tarkka-owned identity, provider observations remain separate, enrichment does not couple providers, and ambiguous identity is represented explicitly rather than silently collapsed.

## Phase 3 — Structured research extraction

Status: **in progress**

Goal: turn normalized documents into reusable research objects.

Foundation deliverables:

- typed Evidence contract with exact passage-local spans
- immutable extraction-run metadata separated from record-level confidence/review provenance
- human review state
- author-stated vs inferred attribution
- typed Claim, Hypothesis, Method, Dataset, Variable, Model, Metric, Result, and Limitation contracts
- provider/model-neutral `StructuredExtractor` port and postcondition validation
- `ExtractionRepository` persistence port with run-scoped reads and atomic/idempotent write semantics
- PostgreSQL reference schema with lineage constraints and evidence validation
- extraction contract tests

Delivered vertical slices now also include:

- deterministic claim extraction
- local JSON extraction repository
- claim/evidence CLI inspection
- provider-neutral structured model boundary
- OpenAI-compatible model adapter
- extraction evaluation fixtures and claim precision/recall metrics
- bounded model requests with request-local evidence validation and overlap deduplication

The supported foundation workflow, failure behavior, debugging steps, and current non-goals are documented in [`MILESTONE_4.md`](MILESTONE_4.md).

Next:

1. generalize bounded structured extraction beyond claims
2. add schema-constrained extraction for Method, Dataset, and Result first
3. expand to Variable, Model, Metric, Limitation, and Hypothesis
4. introduce generalized evidence locators for textual and multimodal source objects
5. add first-class Figure, Table, and Equation document artifacts without requiring OCR/vision
6. add optional native-structure, OCR, and vision adapters behind explicit contracts
7. link figure/table interpretations to source artifacts without overwriting immutable source facts

Multimodal source artifacts should preserve layers explicitly:

```text
immutable Figure/Table/Equation artifact
    -> observed structure/text/value
    -> optional interpretation
    -> Result / Claim / other research object
```

OCR, vision, chart digitization, and embeddings are optional adapters. They are not requirements of the core document or evidence model.

Agents must return evidence-backed records and only concise visible reasoning summaries where useful. Hidden chain-of-thought is never persisted.

Later in this phase:

- software and experiment contracts where the first workflows require them
- richer table/figure reconstruction when native source data are unavailable
- links from figures to supplementary/raw datasets where available

## Phase 4 — Evidence verification

Goal: distinguish citation from actual support.

Deliverables:

- claim/evidence relationships
- verification workflow
- support/contradiction/qualification labels
- confidence and review state
- source passage/figure/table expansion
- deterministic evaluation fixtures

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
- JSON/JSONL and BibTeX/RIS export

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

### Evaluation

Measure parser quality, identity precision/recall, extraction accuracy, evidence verification, retrieval quality, context/token efficiency, latency, and cost.

### Documentation

Every public feature requires user workflow documentation, interface behavior, failure behavior, reproducibility notes, and agent-consumption guidance where applicable.

### Security and rights

Advance controls with deployment scope. Do not advertise institutional readiness before threat modeling, tenancy controls, artifact hardening, and rights-policy enforcement are implemented and tested.
