# Architecture

## Overview

The platform is a research infrastructure system with a domain-agnostic core and replaceable adapters. It should support single-machine use first while preserving contracts that allow institutional deployment later.

```text
                         Clients
        ┌──────────────────┼──────────────────┐
        │                  │                  │
       CLI               REST                MCP
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                  Application Services
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
   Discovery           Ingestion          Research/QA
       │                   │                   │
       └───────────────┬───┴───────────────┬───┘
                       ▼                   ▼
                  Domain/Core Contracts
                       │
       ┌───────────────┼──────────────────────────┐
       ▼               ▼                          ▼
   Provider         Parser/Enricher           Extractor
   adapters            adapters                adapters
       │               │                          │
       └───────────────┼──────────────────────────┘
                       ▼
                   Persistence
            ┌──────────┼──────────┐
            ▼          ▼          ▼
        PostgreSQL   pgvector   Artifact Store
```

## Architectural preservation rule

> **Preserve native structure first; normalize second; infer last.**

External providers and document formats often expose more information than Tarkka has promoted into canonical fields. The architecture must preserve that information without making provider payloads the canonical model.

Three observation layers remain distinct:

```text
native source fact
    ↓
parser-reconstructed observation (optional)
    ↓
inferred interpretation/research object (optional)
```

A JATS bibliography entry, a PDF parser's reconstructed table, and a model's interpretation of a chart are not equivalent facts and must not overwrite one another.

See [`SOURCE_DOCUMENT_PRESERVATION.md`](SOURCE_DOCUMENT_PRESERVATION.md) for the detailed format/source/crawler design.

## Layers

### 1. Interfaces

Interfaces must remain thin and share application services:

- Python SDK
- CLI
- REST API
- MCP server
- Agent Skills
- reporting/export adapters

No interface should duplicate research logic.

### 2. Application services

Orchestrate use cases such as:

- create/sync workspace
- discover works
- acquire artifacts
- resolve identities and duplicates
- parse and enrich documents
- preserve native source observations/resource links
- select adapters by capability
- resolve bibliography/citation relationships
- run extraction contracts
- verify evidence relationships
- build research snapshots
- retrieve context
- compare claims/methods/results
- export reproducible reports

Application services depend on domain contracts, not concrete infrastructure.

### 3. Core domain

The core contains stable concepts and invariants:

- workspace
- topic / research question
- search strategy
- source/provider observation
- capability manifest
- resource link observation
- work
- artifact
- document / section / passage
- figure / table / equation
- author / organization
- bibliography / citation / work relationship
- claim / evidence / evidence relationship
- method / model / variable / metric / dataset / software
- experiment / result / limitation
- extraction/verification record
- snapshot
- rights/provenance record

The domain layer should avoid imports from web frameworks, databases, parser SDKs, or LLM vendors.

### 4. Adapters

External systems implement narrow protocols.

#### Discovery providers

Examples:

- OpenAlex
- Semantic Scholar
- Crossref
- arXiv
- PubMed
- DataCite
- user-defined web/source adapters

Providers may expose different capabilities: search, record lookup, references, citations, full-text links, supplements, or native metadata. Orchestration should select by capability rather than provider-name branching when the capability contract is available.

#### Acquisition adapters

Examples:

- URL HTTP fetcher
- web/sitemap/feed crawler
- local files
- S3-compatible object stores
- permitted institutional connectors
- GitHub / dataset repositories

Acquisition/crawler adapters preserve transport/source observations and resource relationships but do not establish canonical research identity by themselves.

#### Parsers/enrichers

Examples:

- native JATS/XML parsers
- EPUB parsers
- semantic HTML/XHTML parsers
- LaTeX/source-bundle parsers
- Docling
- GROBID
- spreadsheet/tabular parsers
- optional OCR/layout/vision adapters

Prefer the richest available native representation. PDF is an important publication artifact, but it is often a reconstruction source rather than the richest structural source.

#### Extraction engines

Examples:

- deterministic/rule extraction
- JSON-schema constrained LLM extraction
- local models
- Anthropic/OpenAI/OpenAI-compatible providers

Inferred extraction records retain provenance and must not rewrite source-native/reconstructed observations.

#### Retrieval engines

Examples:

- PostgreSQL full-text
- pgvector
- rerankers
- PaperQA2-inspired evidence retrieval

#### Reporting adapters

Examples:

- Quarto
- JSON/JSONL
- Markdown
- CSV/Parquet
- BibTeX/RIS/CSL-JSON

## Source observation architecture

`SourceObservation` is an additive preservation envelope for provider-native, reconstructed, or inferred information.

```text
provider/native payload
      ↓
SourceObservation
      ↓
canonical mapper
      ↓
Work / Document / Relation / Research object
```

Large/raw payloads belong in immutable content-addressed artifacts; observations reference them. Bounded JSON-like metadata can preserve provider fields that are useful but not yet canonical.

This is deliberately not an everything-JSON design: strong canonical concepts remain typed and relational.

The current `WorkSourceRecord` remains valid for scholarly discovery. Existing providers can migrate incrementally when touched rather than through a flag-day rewrite.

## Resource relationship architecture

A discovered URI/resource relationship should be preserved before resolution:

```text
SourceObservation
      ↓
ResourceLinkObservation
      ↓ optional acquisition
Artifact
      ↓ optional identity resolution
Work / Dataset / Software / related resource
```

This supports alternate/full-text representations, supplements, datasets, code, citations, versions, corrections/retractions, and related resources without prematurely asserting identity.

## Document structure architecture

As format adapters mature, documents may preserve/link:

```text
Document
 ├ metadata
 ├ sections / reading order
 │   ├ paragraphs/passages
 │   ├ lists
 │   └ footnotes
 ├ figures + captions
 ├ tables + cells/headers/notes
 ├ equations
 ├ bibliography
 ├ inline citation anchors/context
 ├ internal cross-references
 ├ native IDs/anchors
 └ supplementary/resource links
```

Native format structure and parser-reconstructed structure must remain distinguishable.

## Citation architecture

Do not collapse all citation concepts into one object. Future citation work distinguishes:

```text
CitationMention
     ↓ refers to
BibliographicReference
     ↓ resolves to
Canonical Work
```

The surrounding `CitationContext` remains source-local evidence for later verification. Work-to-Work relations remain typed and provenance-backed. Citation graph traversal must be bounded and does not require a graph database initially.

## Web crawler architecture

Crawler code should remain a discovery/acquisition layer:

```text
URL discovery
  -> HTTP observation
  -> content identification
  -> resource-link discovery
  -> media/format routing
  -> specialized parser or artifact-only preservation
```

Crawler state should preserve canonical/final URLs, redirects, HTTP metadata, sitemap/feed origin, link anchor/context, content type, and bounded traversal checkpoints. It should not directly create canonical Works or embed PDF/HTML research parsing logic.

## Storage architecture

### PostgreSQL

PostgreSQL is the default metadata and relational system of record.

Suggested logical schemas:

```text
catalog.*      source/work/author identifiers and metadata
document.*     artifact/document/section/passage/table/figure
research.*     questions/claims/evidence/methods/results
knowledge.*    concepts/entities/relationships/syntheses
workflow.*     jobs/runs/snapshots/checkpoints
audit.*        provenance/extraction/verification/review events
agent.*        retrieval packages/context manifests/usage telemetry
```

This is a logical starting point, not a commitment to separate physical databases.

Provider-native observation payloads should not create hundreds of provider-specific canonical columns. Preserve raw/native observations separately and promote fields into typed relational structures when the core genuinely depends on them.

### Vector retrieval

Use pgvector initially. Do not introduce a separate vector database until measurements justify the operational complexity.

### Artifact storage

Raw and derived files should live outside ordinary relational rows using content-addressed storage.

```text
sha256:<digest>
```

A content hash becomes a stable artifact identity and enables deduplication, caching, reproducibility, integrity checks, and cheap change detection.

The first implementation may use the local filesystem; S3-compatible storage should be an adapter.

## Deployment profiles

### Developer/local

```text
processes: CLI + API/MCP as needed
metadata: PostgreSQL (or optional lightweight dev profile later)
artifacts: local filesystem
queue: in-process
models: local or remote
```

### Team/server

```text
API/MCP
PostgreSQL + pgvector
S3/MinIO
worker processes
queue
observability
```

### Institutional

Add without changing core contracts:

- organizations/workspaces
- SSO/OIDC
- RBAC/ABAC
- quotas
- audit retention
- encrypted object storage
- worker pools
- policy enforcement
- secrets management
- backups/disaster recovery
- tracing/metrics/logging

## Dependency rule

Dependencies point inward:

```text
interfaces -> application -> domain
adapters    -> application/domain contracts
infrastructure -> domain/application contracts
```

The domain layer does not know whether a document came from OpenAlex, a JATS repository, an EPUB, a PDF upload, a crawler, a local folder, or a future connector.

## Extension strategy

### Capability-aware plugins

Plugins add capabilities such as providers, parsers, extractors, exporters, crawlers, or storage backends. Small capability manifests should let orchestration and agents discover installed functionality without loading implementation-specific documentation.

Prefer explicit registration/entry points after multiple real adapters exercise the contracts. Avoid filesystem magic or a heavyweight plugin framework prematurely.

### Domain packs

Domain packs add semantic configuration:

- ontology/vocabulary
- source catalog
- extraction schemas
- evidence/quality policies
- research templates
- domain-specific agent skills
- optional downstream integration mappings

Domain packs must not fork the core persistence or orchestration model.

## Why not GraphRAG first?

The system needs explicit relationships, including citations and resource links, but those can initially be represented relationally and exposed as graph projections. A dedicated graph store should only be introduced when measured retrieval/query needs justify it.

## Key architectural tests

The architecture is healthy if:

1. Replacing OpenAlex with another provider does not change domain/application code.
2. Replacing an LLM provider does not change extraction contracts.
3. Adding JATS/EPUB/HTML support does not require rewriting PDF/document consumers.
4. Provider fields Tarkka does not yet normalize can be retained without canonical schema redesign.
5. Source-native facts, reconstructed observations, and inferred interpretations remain distinguishable.
6. Adding a new crawler/source primarily requires an adapter/capability implementation rather than core branching.
7. Adding finance does not require modifying baseball-specific code because baseball-specific code is outside core.
8. CLI and MCP return equivalent research objects from the same service layer.
9. Retrieval can return a 300-token manifest before loading a 30,000-token source.
10. Every derived claim can resolve back to source evidence when evidence exists.
11. Bibliographic/citation relationships can remain unresolved without losing the original source representation.
12. A sync after no source changes does nearly no expensive work.
