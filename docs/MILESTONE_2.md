# Milestone 2 — Document Normalization and Quality Gates

## Goal

Move Tarkka from a text-only kernel to a replaceable rich-document normalization pipeline without
making Docling, a database, a network connection, or an LLM mandatory for the core runtime.

## Delivered in this milestone

### Optional Docling adapter

`DoclingParser` implements the existing `DocumentParser` port and converts Docling's modern v2
`DoclingDocument` output into Tarkka's canonical document hierarchy.

The adapter is optional:

```bash
pip install -e '.[docling]'
```

Plain text and Markdown remain usable without it.

### Shared normalization contract

Parser outputs converge on:

```text
Artifact
  -> Document
      -> Section
          -> Passage
```

The shared Markdown normalizer provides deterministic character offsets and hierarchy for current
adapters. Future parsers may preserve richer native structures, but they must satisfy the same core
entity invariants.

### Defensive text handling

Tarkka replaces embedded NUL characters in Docling's exported normalized text before persistence.
The immutable raw artifact remains untouched. This prevents text-storage truncation while leaving a
visible replacement marker for later inspection.

### Acquisition provenance

Artifact content identity and acquisition history are now separate concepts. Multiple acquisition
events can point to one content-addressed artifact.

This supports future flows such as:

- local upload + DOI resolution of the same paper
- multiple repository mirrors
- repeated synchronization over time
- source/provider audit trails

PostgreSQL receives a dedicated `tarkka.acquisition` table; the local runtime uses an append-only
JSONL acquisition log.

### Automated quality gates

GitHub Actions validates:

- Ruff
- strict mypy
- pytest
- Python 3.11, 3.12, and 3.13 core compatibility
- optional Docling installation/import on Python 3.12

Parser-contract tests validate canonical identity, ordinal, section, passage, and character-range
invariants independently of a particular parser vendor.

## Explicitly deferred

This milestone does **not** yet add:

- GROBID scholarly enrichment
- native table/figure/equation entities from Docling
- page/bounding-box provenance
- OpenAlex/Crossref/Semantic Scholar discovery
- pgvector retrieval
- LLM extraction
- MCP/API serving

Those should build on the now-stable parsing boundary rather than bypassing it.

## Next milestone

Scholarly discovery and identity resolution:

1. provider-neutral discovery contracts
2. OpenAlex adapter
3. Crossref DOI/metadata enrichment
4. Semantic Scholar adapter
5. canonical external-ID aliases and deduplication
6. resumable provider pagination/rate-limit handling
7. search snapshots for reproducibility
