# Project Charter

## Working title

**Thoth** is the current repository name only. The final project name is intentionally unresolved; see `docs/NAMING.md`.

## Mission

Build a free, open-source, domain-agnostic research infrastructure platform that turns heterogeneous research sources into structured, evidence-linked, reproducible, agent-friendly knowledge.

## Problem

Research is fragmented across papers, websites, reports, books, datasets, code repositories, institutional publications, spreadsheets, presentations, and private collections. Existing tools usually solve only one layer:

- discovery without durable organization,
- document chat without structured extraction,
- systematic review workflows without agent-oriented serving,
- vector search without evidence lineage,
- citation generation without claim verification,
- notebooks without reusable research state,
- agent tools without token-efficient knowledge contracts.

The project should connect these layers without coupling the system to one research domain, one LLM provider, one parser, or one retrieval strategy.

## Primary users

- independent researchers
- students and educators
- data scientists and quantitative researchers
- software engineers and AI-agent developers
- research teams and laboratories
- analysts in finance, economics, sports, policy, law, medicine, and other evidence-heavy fields
- institutions that need self-hosted or governed research infrastructure

## Core outcomes

A user should be able to:

1. Define a research workspace and research questions.
2. Configure source providers and search strategies.
3. Import local or remote research artifacts.
4. Deduplicate and resolve canonical works and identifiers.
5. Parse heterogeneous documents into a common representation.
6. Extract structured research objects such as claims, methods, variables, datasets, models, metrics, results, limitations, and citations.
7. Verify claim-to-evidence relationships.
8. Preserve provenance and rights metadata for every important derived object.
9. Search semantically, lexically, structurally, and by metadata.
10. Ask agents questions without sending entire corpora into model context.
11. Progressively retrieve evidence only when needed.
12. Compare findings, contradictions, replications, methods, and evidence quality.
13. Export reproducible reports and research artifacts.
14. Connect research findings to downstream experiments, code, models, or domain-specific databases.
15. Re-run or incrementally update a research workspace later.

## Non-goals for the initial release

- replacing academic search engines
- hosting copyrighted full-text content for redistribution
- becoming a general-purpose web crawler before research contracts are stable
- building a bespoke vector database
- building a new LLM framework
- implementing a knowledge graph database before relational and retrieval requirements justify one
- reproducing every feature of Zotero, PaperQA2, Docling, GROBID, Quarto, or systematic-review software
- solving institutional governance before a single-user reference implementation works well

## Architectural principles

### Evidence before eloquence

Generated synthesis is secondary to verifiable evidence. The system must make it cheap to answer: "Where did this come from?"

### Progressive disclosure

Large context should never be the default. Metadata, summaries, and indexes are presented first; details are fetched sequentially as the consumer demonstrates need.

### Stable core, replaceable integrations

External providers and engines are adapters behind explicit interfaces.

### Domain packs, not domain forks

Baseball, finance, medicine, and other domains should extend a shared research model with vocabularies, extraction schemas, source catalogs, validation rules, and skills.

### Reproducible by construction

Queries, source versions, parser versions, model versions, prompts/extraction contracts, timestamps, git revisions, and research snapshots should be recordable.

### Rights-aware by construction

Content access, storage, transformation, redistribution, and commercial-use permissions are separate concerns and should be modeled separately.

### Human verification is first-class

Automated extraction and verification may be uncertain. Human review states and corrections must be representable without destroying the machine-generated history.

## Reference validation domains

### Baseball / MLB

Validate support for:

- scholarly and practitioner research
- sabermetric methods
- model and feature extraction
- temporal leakage rules
- source-to-feature-to-experiment lineage
- prediction/backtest research

### Finance / economics

Validate support for:

- institutional research and academic papers
- factors, hypotheses, variables, models, datasets, and empirical results
- conflicting findings and replication
- time-sensitive revisions
- strong licensing/provenance boundaries

## Success criteria for v1

A v1 is successful when a new user can configure a workspace, discover and ingest a modest corpus, normalize and index documents, obtain structured evidence-linked research objects, query them through both CLI and MCP, and generate a reproducible report without hand-editing internal database state.

## Open-source intent

The core is intended to be free and open source. A permissive or weak-copyleft license should be selected after dependency and commercialization review. The project must keep software licensing separate from source-content rights.
