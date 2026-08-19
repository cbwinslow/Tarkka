# Roadmap

## Strategy

Build the smallest coherent vertical slice first, then expand through adapters and domain packs. Avoid implementing every possible source or enterprise feature before the core contracts are validated.

## Phase 0 — Foundation

Status: **in progress**

Deliverables:

- project charter
- architecture
- canonical data model
- pipeline stages
- plugin contracts
- agent interface
- context-efficiency design
- security/rights baseline
- naming decision
- initial contribution/development guidance

Exit criteria:

- architecture can be explained without naming a single mandatory vendor
- first canonical entities and service boundaries are stable enough to implement

## Phase 1 — Core local vertical slice

Goal: ingest local research and query evidence on one machine.

Deliverables:

- Python package skeleton
- typed domain models
- PostgreSQL migrations
- local content-addressed artifact store
- workspace service
- user file acquisition
- one general document parser adapter (likely Docling evaluation)
- normalized document/section/passage persistence
- deterministic chunk/index pipeline
- PostgreSQL full-text + pgvector retrieval
- CLI
- structured logging
- pytest contract/unit tests

Demo:

```text
research init
research ingest ./papers
research search "pitcher fatigue"
research get <work-id>
```

## Phase 2 — Scholarly discovery and identity

Goal: build research collections from a topic instead of manual files only.

Deliverables:

- OpenAlex adapter
- Crossref identity/enrichment adapter
- Semantic Scholar adapter
- arXiv adapter
- canonical work resolution
- deduplication
- resumable pagination
- provider rate-limit orchestration
- search snapshots

Demo:

```text
research discover "MLB game outcome prediction" --providers openalex,semantic-scholar
research sync
```

## Phase 3 — Structured research extraction

Goal: turn documents into reusable research objects.

Deliverables:

- extraction-contract format
- schema-constrained extractor interface
- one cloud-model adapter and one OpenAI-compatible/local path
- claims
- methods/models
- variables
- metrics
- datasets/software
- experiments/results
- limitations
- extraction provenance
- human review state

## Phase 4 — Evidence verification

Goal: distinguish citation from support.

Deliverables:

- claim/evidence relationships
- verification workflow
- contradiction/qualification labels
- confidence and review state
- source passage expansion
- evaluation fixtures

## Phase 5 — Agent-first serving

Goal: make Claude/Codex/custom agents efficient research consumers.

Deliverables:

- MCP server
- compact capability discovery
- manifest/summary/evidence/full expansion ladder
- context-package service
- stable handles/saved result collections
- portable Agent Skills
- token/cost telemetry

Benchmarks:

- context tokens per task
- evidence recall/precision
- answer faithfulness
- number of expansion operations
- latency

## Phase 6 — Reproducible outputs

Goal: convert research state into durable publications.

Deliverables:

- Quarto exporter
- bibliography generation
- evidence-linked reports
- research snapshot manifests
- JSON/JSONL and BibTeX/RIS export

## Phase 7 — First domain pack: Baseball

Goal: prove integration into `mlb-baseball`.

Deliverables:

- baseball ontology/vocabulary
- SABR/MLB/Statcast-oriented source catalog where permitted
- baseball research extraction rules
- ML-method extraction
- leakage/evidence-quality policy
- paper-to-feature candidate mapping
- paper-to-experiment handoff
- integration example with MLB research/model registry

## Phase 8 — Second domain pack: Finance/Economics

Goal: prove the core is genuinely domain-agnostic.

Deliverables:

- finance/economics vocabulary
- academic/economic source catalog
- factor/model/variable extraction
- finance-specific quality observations such as lookahead/survivorship bias and transaction-cost treatment
- FRED/SEC/NBER/CFA-style source adapters or user-provided-content workflows where rights permit

## Phase 9 — Team/institutional scaling

Only after core workflows are measured and useful.

Deliverables may include:

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

Create benchmark corpora and measure:

- parser quality
- deduplication precision/recall
- extraction accuracy
- evidence verification accuracy
- retrieval quality
- context/token efficiency
- latency/cost

### Documentation

Every public feature requires:

- user workflow documentation
- API/CLI documentation
- agent consumption guidance
- failure behavior
- reproducibility notes

### Security

Security milestones advance with deployment scope; do not advertise institutional readiness before threat modeling and tenancy controls exist.

## First coding milestone

The recommended first implementation PR should contain only:

1. package skeleton and development tooling
2. typed core IDs/entities for Workspace, Work, Artifact, Document, Section, Passage
3. adapter protocols
4. PostgreSQL connection/migration foundation
5. local content-addressed artifact store
6. a single end-to-end test proving `file -> artifact -> document manifest`

Everything else builds on that vertical slice.
