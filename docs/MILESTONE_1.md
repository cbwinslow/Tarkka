# Milestone 1 — Core Research Kernel

## Scope

This milestone establishes the smallest runnable Tarkka vertical slice while preserving the
architecture documented in the foundation PR.

## Implemented

- lowercase `tarkka` Python package and CLI namespace
- immutable typed core entities for Workspace, Work, Artifact, Document, Section, and Passage
- narrow ports for artifact storage, document parsing, and metadata persistence
- local immutable SHA-256 content-addressed artifact store
- deterministic bootstrap parser for UTF-8 text/Markdown
- offline JSON research catalog for the local reference runtime
- PostgreSQL schema migration and optional psycopg connection boundary
- compact progressive-disclosure resource manifests with token estimates
- shared ingestion application service
- `tarkka ingest`, `tarkka inspect`, and `tarkka read`
- deterministic end-to-end and domain-invariant tests

## Deliberately deferred

- PDF parsing / Docling integration
- GROBID scholarly enrichment
- OpenAlex/Crossref/Semantic Scholar discovery
- pgvector/full-text retrieval
- LLM extraction
- claim/evidence semantics
- MCP/API interfaces
- Quarto output

These are later roadmap phases and should be added through the ports established here.

## Local runtime

The local runtime uses two independent stores:

1. immutable artifact bytes under `$TARKKA_HOME/artifacts/sha256/...`
2. normalized metadata in `$TARKKA_HOME/catalog.json`

This is a bootstrap/offline implementation, not a replacement for PostgreSQL. The JSON adapter is
useful for development, demos, agent sandboxes, and tests where external infrastructure should not
be mandatory.

## Progressive disclosure

`ingest` and `inspect` emit a small YAML-frontmatter-compatible manifest rather than document text.
Agents can inspect structure and estimated full-text size before requesting content using `read`.

This validates the project principle: **metadata first, detail on demand**.
