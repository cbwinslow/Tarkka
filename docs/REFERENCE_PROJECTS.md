# Reference Projects and Components

## Purpose

This project should integrate, wrap, learn from, or interoperate with proven components rather than reimplementing everything.

This document is an evaluation catalog, **not** a dependency lockfile or endorsement of every architecture choice in the referenced projects.

## Research discovery and scholarly metadata

### OpenAlex

Potential role:

- scholarly work discovery
- authors/institutions/concepts
- citation graph metadata
- open-access metadata

Integration stance: discovery/enrichment adapter.

### Semantic Scholar

Potential role:

- scholarly paper discovery
- citation/reference metadata
- relevance signals and paper graph data

Integration stance: discovery/enrichment adapter.

### Crossref

Potential role:

- DOI resolution
- canonical publication metadata
- publisher/venue metadata
- license/update metadata when available

Integration stance: identity/enrichment adapter.

### arXiv

Potential role:

- preprint discovery and identifiers
- accessible source artifacts where terms permit

Integration stance: discovery/acquisition adapter.

## Evidence-oriented research systems

### PaperQA2 / PaperQA

Ideas to evaluate:

- evidence-focused retrieval over scientific papers
- metadata resolution
- evidence gathering/reranking
- citation-grounded synthesis

Stance: use or wrap where it solves the problem well; do not make the canonical data model depend on PaperQA internals.

### SLR-Engine

Ideas to study:

- reproducible systematic-review stages
- deduplication and acquisition flow
- screening/audit trail
- citation snowballing
- structured extraction
- agent skill integration

Stance: strong architectural reference for resumable research workflows.

### Thoth (existing external project)

Ideas to study:

- claim-level citation verification
- agentic systematic review
- MCP exposure
- evaluation/observability

Important: this is also why the current repository name should change.

### HyperResearch

Ideas to study:

- persistent research knowledge base
- academic-first discovery with web supplementation
- living research workspace/wiki concepts

### Universal SLR Assistant

Ideas to study:

- model-provider abstraction
- local/remote inference interoperability

## Document normalization

### Docling

Potential role:

- general-purpose normalization of PDFs, office documents, HTML, images, and other formats
- layout/table/formula extraction
- unified document representation

Stance: likely reference parser adapter; evaluate carefully rather than reproducing its parsing work.

### GROBID

Potential role:

- scholarly PDF metadata
- bibliography/reference parsing
- citation context
- authors/affiliations
- structured scientific full text

Stance: scholarly enrichment/parser adapter, potentially used alongside general parsing.

## Reporting and reproducibility

### Quarto

Potential role:

- reproducible research reports
- computational documents
- citations/bibliographies
- HTML/PDF/DOCX/site output
- publication-quality research artifacts

Stance: exporter/reporting adapter. PostgreSQL/research objects remain system of record.

## Retrieval and storage

### PostgreSQL

Reference system of record for normalized metadata, research objects, audit data, and workflow state.

### pgvector

Reference first vector-retrieval implementation to avoid unnecessary infrastructure.

### S3-compatible object storage

Reference scalable artifact-storage interface. Local filesystem is acceptable for the first profile.

## Concepts worth evaluating separately

- lexical + vector hybrid retrieval
- reranking
- hierarchical summarization / RAPTOR-like concepts
- query transformation such as HyDE where measured useful
- citation graph expansion / snowballing
- local embedding/reranking models
- structured-output validation
- dataset/code linkage
- retraction/correction monitoring

None of these should be enabled merely because they are fashionable. Add them behind contracts and benchmark them against simpler baselines.

## Build vs. integrate rule

Before implementing a substantial subsystem, answer:

1. Does a mature open-source project already solve this well?
2. Can it be wrapped behind our canonical interface?
3. Is its license compatible with our intended distribution?
4. Does adopting it leak its data model into our core?
5. Can it run locally/self-hosted where required?
6. What happens if it is replaced later?
7. Do we have a benchmark showing custom work would improve a real requirement?

## Dependency governance

Every major adopted component should eventually have a short decision record covering:

- reason for adoption
- alternatives considered
- license
- security/update posture
- operational footprint
- data sent externally
- replacement boundary
