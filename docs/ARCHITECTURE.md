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
- source/provider
- work
- artifact
- document / section / passage
- author / organization
- citation
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
- user-defined web/source adapters

#### Acquisition adapters

Examples:

- URL HTTP fetcher
- local files
- S3-compatible object stores
- permitted institutional connectors
- GitHub / dataset repositories

#### Parsers/enrichers

Examples:

- Docling
- GROBID
- native HTML/Markdown parsers
- JATS/XML parsers
- spreadsheet/tabular parsers

#### Extraction engines

Examples:

- deterministic/rule extraction
- JSON-schema constrained LLM extraction
- local models
- Anthropic/OpenAI/OpenAI-compatible providers

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
- BibTeX/RIS

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

The domain layer does not know whether a document came from OpenAlex, a PDF upload, CFA content, a local folder, or a future connector.

## Extension strategy

### Plugins

Plugins add capabilities such as providers, parsers, extractors, exporters, or storage backends.

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

The system needs explicit relationships, but those can initially be represented relationally and exposed as graph projections. A dedicated graph store should only be introduced when measured retrieval/query needs justify it.

## Key architectural tests

The architecture is healthy if:

1. Replacing OpenAlex with another provider does not change domain/application code.
2. Replacing an LLM provider does not change extraction contracts.
3. Adding finance does not require modifying baseball-specific code because baseball-specific code is outside core.
4. CLI and MCP return equivalent research objects from the same service layer.
5. Retrieval can return a 300-token manifest before loading a 30,000-token source.
6. Every derived claim can resolve back to source evidence when evidence exists.
7. A sync after no source changes does nearly no expensive work.
