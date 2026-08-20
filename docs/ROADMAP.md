# Roadmap

## Strategy

Build the smallest coherent vertical slice first, then expand through adapters and domain packs. Avoid implementing every possible source, model provider, or enterprise feature before the core contracts are measured and validated.

Milestone numbers in implementation PRs map to the phases below; the phase names are the authoritative long-term sequence.

## Current status

- Phase 0 — Foundation: **complete**
- Phase 1 — Core local vertical slice: **substantially complete**
- Phase 2 — Scholarly discovery and identity: **in progress**
- Phase 3 — Structured research extraction: **next major phase**

The merged implementation already includes the typed core, content-addressed local artifacts, normalized documents, Docling adapter, acquisition provenance, CLI, CI, provider-neutral discovery, OpenAlex/Crossref/Semantic Scholar adapters, provider selection, pagination, resilient HTTP behavior, SearchSnapshots, and conservative DOI-first identity grouping.

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

Remaining Phase 1 work that can proceed when required by downstream features:

- PostgreSQL repositories for the full canonical model
- structured logging/observability hooks
- PostgreSQL full-text + pgvector retrieval
- deterministic chunk/index pipeline beyond the current passage model

## Phase 2 — Scholarly discovery and identity

Status: **in progress**

Goal: build reproducible research collections from topics rather than manual files only.

Delivered:

- provider-neutral discovery contracts
- replaceable `ProviderSelector`
- `auto`, explicit-provider, and `all` modes
- OpenAlex discovery adapter
- Crossref discovery adapter
- Semantic Scholar discovery adapter
- bounded concurrent fan-out
- resilient HTTP retries/rate-limit handling
- provider-specific continuation cursors
- SearchSnapshots
- shared DOI normalization/validation
- conservative DOI-first canonical identity grouping
- `tarkka discover`

Next:

1. persistent canonical `Work` identity
2. external-ID aliases and provenance per work
3. Crossref DOI enrichment service
4. arXiv specialized discovery/full-text adapter
5. richer query-intent/capability routing
6. explicit fuzzy identity candidates with confidence/evidence; never silent fuzzy merges

Exit criteria:

- a discovered work can be persisted once while retaining aliases/observations from multiple providers
- enrichment can add or reconcile metadata without providers calling one another directly
- discovery can be replayed/audited from snapshots
- ambiguous identity is represented explicitly rather than silently collapsed

## Phase 3 — Structured research extraction

Goal: turn normalized documents into reusable research objects.

Deliverables:

- extraction-contract format
- schema-constrained extractor interface
- deterministic extraction stages where possible
- one cloud-model adapter and one OpenAI-compatible/local path
- claims
- methods/models
- variables
- metrics
- datasets/software
- hypotheses
- experiments/results
- limitations
- extraction provenance/versioning
- human review state

## Phase 4 — Evidence verification

Goal: distinguish citation from actual support.

Deliverables:

- claim/evidence relationships
- verification workflow
- support/contradiction/qualification labels
- confidence and review state
- source passage expansion
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

### Evaluation

Measure parser quality, identity precision/recall, extraction accuracy, evidence verification, retrieval quality, context/token efficiency, latency, and cost.

### Documentation

Every public feature requires user workflow documentation, interface behavior, failure behavior, reproducibility notes, and agent-consumption guidance where applicable.

### Security and rights

Advance controls with deployment scope. Do not advertise institutional readiness before threat modeling, tenancy controls, artifact hardening, and rights-policy enforcement are implemented and tested.
