# Open Questions

These questions are intentionally unresolved. They should be answered with prototypes, benchmarks, licensing review, or user feedback rather than assumption.

Resolved decisions should be removed from this file and reflected in the appropriate architecture/development document so agents do not repeatedly reopen them.

## Open-source license

- Apache-2.0, MIT, MPL-2.0, AGPL-3.0, or another license?
- How much do we want hosted commercial modifications to remain open?
- Which choice best balances institutional adoption and ecosystem contribution?

## Persistence

- Should the current thin PostgreSQL approach remain intentionally small, or should SQLAlchemy/Alembic become worthwhile as persistent Work/evidence models grow?
- Should the lightweight local profile eventually support SQLite, or would that create too much behavioral divergence from PostgreSQL?
- Which future research entities should be immutable/versioned versus mutable with audit history?

## Parsing

- Is Docling the best default general parser after benchmarking representative corpora?
- When should GROBID enrich scholarly parsing?
- Which parser-specific structures should be retained beyond the current canonical `Document -> Section -> Passage` representation?

## Scholarly identity and enrichment

- Which external identifiers besides DOI should participate in automatic canonical identity versus remain aliases/observations?
- What evidence threshold should allow fuzzy title/author/year candidates to be proposed?
- Which conflicts should enrichment resolve automatically versus preserve as competing source observations?
- When should Crossref enrichment run automatically, selectively, or only when explicitly requested?

## Discovery routing

- What query features justify using more than one provider in `auto` mode?
- Should provider health, credentials, rate limits, expected coverage, and latency/cost become inputs to a formal routing score?
- How should domain packs influence provider selection without coupling core discovery to one domain?

## Extraction

- What is the first extraction-contract format: JSON Schema, Pydantic-derived schema, or another typed contract?
- Which tasks should remain deterministic and which justify LLM assistance?
- What evaluation corpus proves extraction quality across at least two domains?
- How should extractor/model versions participate in provenance and re-extraction decisions?

## Retrieval

- What hybrid lexical/vector strategy provides the best evidence recall at low context cost?
- When does reranking materially help?
- Which hierarchical-summary strategy is worth the maintenance cost?
- When, if ever, is a dedicated graph database justified beyond relational graph projections?

## MCP/tool design

- How small can the top-level tool surface remain while still being ergonomic?
- Should detailed operation schemas be exposed as resources, subcommands, or typed operation arguments?
- How should token/size estimates be reported consistently across clients?
- Which capability-discovery pattern works best across Claude, Codex, and generic MCP clients?

## Rights and content policy

- What source-policy schema is practical across academic, public-web, licensed, and user-provided sources?
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
- What identity-resolution precision threshold is required before any fuzzy merge can be automated?

## Product direction

- Is the long-term project primarily a library, server, developer platform, or all three with one reference server?
- Should a first-party UI exist in v1, or should CLI/MCP/Quarto prove the core before UI investment?
