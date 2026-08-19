# Thoth (working name)

> A domain-agnostic, evidence-first research infrastructure platform for humans and AI agents.

**Project name is provisional.** See [`docs/NAMING.md`](docs/NAMING.md).

## Vision

Thoth turns scattered research into structured, reproducible, inspectable knowledge that humans and AI agents can use efficiently.

It is not another "chat with PDFs" application. The system is designed to discover, ingest, normalize, enrich, extract, verify, organize, retrieve, compress, and serve research while preserving lineage back to original evidence.

A user should be able to define a research topic, connect permitted sources, ingest local or remote material, and obtain a reusable research workspace containing structured objects such as:

- works, authors, organizations, datasets, and software
- sections, passages, figures, tables, and citations
- claims, hypotheses, methods, variables, models, metrics, experiments, and results
- evidence relationships such as supports, contradicts, partially-supports, and mentions
- provenance, extraction metadata, rights metadata, confidence, and verification state

The same core platform should support many domains through configuration and domain packs: baseball analytics, finance, economics, medicine, public policy, law, engineering, and others.

## Core design principles

1. **Domain-agnostic core** — domain meaning belongs in reusable domain packs, not core infrastructure.
2. **Evidence-first** — every important derived claim should remain traceable to supporting source material.
3. **Progressive disclosure** — agents receive compact metadata first and load detail only when needed.
4. **Provider-neutral** — Claude, Codex, ChatGPT, local models, and custom agents use the same backend contracts.
5. **Adapter-driven** — discovery providers, parsers, model providers, storage systems, and exporters are replaceable.
6. **Reproducible** — research queries, snapshots, versions, extraction settings, and code revisions are recorded.
7. **Incremental** — repeated syncs process only new or changed material whenever possible.
8. **Local-first, institution-ready** — the same architecture should scale from a laptop to a multi-user deployment.
9. **Rights-aware** — provenance, licensing, redistribution, and usage restrictions are first-class metadata.
10. **Agent-efficient** — token usage, retrieval depth, context assembly, caching, and compression are explicit system concerns.

## Conceptual pipeline

```text
Discover -> Acquire -> Resolve -> Parse -> Normalize -> Enrich
        -> Extract -> Verify -> Index -> Synthesize -> Serve
```

Raw documents are never the only representation. The platform builds a hierarchy:

```text
Source artifact
  -> structured document
    -> section
      -> passage/evidence
        -> claim/method/result
          -> topic synthesis
```

Agents start near the top of the hierarchy and descend only when they need stronger evidence or more detail.

## Planned interfaces

- Python SDK
- CLI
- REST API
- MCP server
- portable Agent Skills (`SKILL.md`)
- Quarto export/reporting integration

These interfaces should expose the same underlying application services rather than implement independent business logic.

## Initial technology direction

The exact components remain adapter choices, but the first reference implementation is expected to evaluate or integrate:

- PostgreSQL + pgvector
- content-addressed object/artifact storage
- OpenAlex, Semantic Scholar, Crossref, arXiv, and user-provided sources
- Docling for broad document normalization
- GROBID for scholarly metadata/citation enrichment
- PaperQA2-style evidence retrieval workflows
- Quarto for reproducible research output
- MCP for agent interoperability

See [`docs/REFERENCE_PROJECTS.md`](docs/REFERENCE_PROJECTS.md) for the projects and ideas we intend to evaluate rather than blindly reimplement.

## Repository status

This repository is intentionally starting **documentation-first**. The goal is to stabilize contracts and architecture before creating a large implementation surface.

Start here:

1. [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md)
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
3. [`docs/CANONICAL_DATA_MODEL.md`](docs/CANONICAL_DATA_MODEL.md)
4. [`docs/RESEARCH_PIPELINE.md`](docs/RESEARCH_PIPELINE.md)
5. [`docs/AGENT_INTERFACE.md`](docs/AGENT_INTERFACE.md)
6. [`docs/CONTEXT_EFFICIENCY.md`](docs/CONTEXT_EFFICIENCY.md)
7. [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Reference domains

The first two validation domains should be deliberately different:

- **MLB/baseball research** — predictive modeling, sabermetrics, Statcast, model features, backtesting, leakage, odds/markets.
- **Finance/economics research** — academic research, CFA-style institutional research where permitted, economic data, factor/model research, reproducibility, and empirical validation.

If the same core architecture works well for both, that is strong evidence the system is genuinely reusable.

## License

A project license has **not yet been selected**. We intend the core to be free and open source, but the license should be chosen deliberately before external contributions are accepted. Source documents and datasets retain their own licenses and terms; this software must never imply that ingesting content grants redistribution or commercial-use rights.

See [`docs/SECURITY_PRIVACY_LICENSING.md`](docs/SECURITY_PRIVACY_LICENSING.md).
