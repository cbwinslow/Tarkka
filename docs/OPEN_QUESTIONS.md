# Open Questions

These questions are intentionally unresolved. They should be answered with prototypes, benchmarks, licensing review, or user feedback rather than assumption.

## Naming

- What final name has the best conceptual fit and namespace availability?
- Should the project use a unique compound name instead of a single mythological name?

## Open-source license

- Apache-2.0, MIT, MPL-2.0, AGPL-3.0, or another license?
- How much do we want hosted commercial modifications to remain open?
- Which choice best balances institutional adoption and ecosystem contribution?

## Persistence

- SQLAlchemy + Alembic vs a thinner PostgreSQL layer?
- Should the lightweight local profile eventually support SQLite, or would that create too much behavioral divergence from PostgreSQL?
- Which entities should be immutable/versioned versus mutable with audit history?

## Parsing

- Is Docling the best default general parser after benchmarking representative corpora?
- When should GROBID enrich or replace general scholarly parsing?
- What normalized document representation preserves enough structure without coupling us to one parser?

## Extraction

- What is the first extraction-contract format: JSON Schema, Pydantic-derived schema, or another typed contract?
- Which tasks are deterministic versus LLM-assisted?
- What evaluation corpus proves extraction quality?

## Retrieval

- What hybrid lexical/vector strategy provides the best evidence recall at low context cost?
- When does reranking materially help?
- Which hierarchical-summary strategy is worth the maintenance cost?
- When, if ever, is a dedicated graph database justified?

## MCP/tool design

- How small can the top-level tool surface remain while still being ergonomic?
- Should detailed operation schemas be exposed as resources, subcommands, or typed operation arguments?
- How should token/size estimates be reported consistently across clients?

## Rights and content policy

- What source-policy schema is practical across academic, public-web, and user-provided sources?
- Which derived research objects can be safely exported independently from restricted full text?
- How should source terms changes be tracked over time?

## Institutional architecture

- At what point should durable queues/workers become mandatory?
- What is the correct tenant-isolation strategy?
- Which authentication/authorization standards should be reference implementations?

## Domain packs

- How much ontology belongs in YAML/configuration versus Python types/plugins?
- What is the minimum reusable contract that works for both baseball and finance?
- How do downstream experiment registries link to generic research objects without polluting core?

## Evaluation

- What benchmark tasks define success for agent context efficiency?
- What is an acceptable claim-evidence verification error rate?
- How do we measure research synthesis usefulness without relying only on LLM-as-judge?

## Product direction

- Is the long-term project primarily a library, server, developer platform, or all three with one reference server?
- Should a first-party UI exist in v1, or should CLI/MCP/Quarto prove the core before UI investment?
