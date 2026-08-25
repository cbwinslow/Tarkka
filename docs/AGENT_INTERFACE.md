# Agent Interface

## Goal

Make the platform equally usable by Claude, Codex, ChatGPT, IDE agents, local agents, and custom automation without encoding vendor-specific behavior in the research core.

## Interface principle

Agents consume **stable research services**, not raw database tables.

The same application services should power:

- MCP
- CLI
- REST
- Python SDK
- portable Agent Skills

## Minimal agent capability families

### Discover

Find candidate research and source coverage.

Typical operations:

- search providers
- preview search strategy
- inspect provider coverage
- paginate/rank candidate works

### Search

Search the normalized research warehouse.

Targets may include:

- works
- claims
- methods
- variables
- datasets
- results
- concepts
- evidence

### Get / Expand

Resolve durable IDs and progressively load more detail.

Examples:

```text
get(work_id, representation="manifest")
expand(work_id, include=["claims", "methods"])
expand(claim_id, include=["evidence"])
```

### Compare

Structured comparison across research objects.

Examples:

- compare claims
- compare methods
- compare study designs
- compare results/metrics
- find contradictions
- find replications

### Verify

Run or retrieve evidence verification for claims/citations.

### Sync

Run a configured research pipeline or inspect sync plans/status.

### Export

Produce Quarto or structured exports.

## MCP design

Prefer a compact MCP tool surface with rich, progressive results over one tool per provider/table/action.

A possible first surface:

```text
research_capabilities
research_search
research_get
research_expand
research_compare
research_verify
research_sync
research_export
```

### Initial delivered stdio transport

The initial `tarkka-mcp` server intentionally implements the smallest useful read-only subset of
that surface:

```text
research_capabilities
research_operation_schema
document_manifest
document_sections
document_section
```

`research_capabilities` remains the first call; it advertises transport-neutral operation handles
without eagerly exposing every argument schema. `research_operation_schema` then loads one schema.
The document tools preserve the same manifest-to-section disclosure ladder as the CLI. They return
structured `ok`/`error` envelopes, stable error codes, and next-action hints rather than requiring
clients to parse process stderr. Every initial tool is annotated read-only and idempotent.

The server is an optional `mcp` extra and uses stdio. It shares the document runtime selection with
the CLI: `TARKKA_DOCUMENT_BACKEND=json` remains the dependency-free default, while an explicitly
configured PostgreSQL backend reads the same persisted document records. No MCP operation currently
writes state, runs schema migrations, calls a provider, or bypasses application services.

Provider-specific details should be selected through typed arguments/resources where possible.

## MCP resources

Resources are useful for relatively stable or navigational information:

- workspace manifest
- domain pack manifest
- provider catalog
- extraction contract catalog
- quality-policy description
- snapshot manifest
- schema/capability descriptors

Large resources should support paging or targeted reads rather than forcing complete transfer.

## Agent response envelope

Every retrieval response should include enough metadata for an agent to decide whether expansion is worthwhile.

Conceptual envelope:

```yaml
query_id: q_...
representation: manifest
count: 12
estimated_tokens: 840
items:
  - id: work:...
    type: work
    title: ...
    relevance: 0.91
    available:
      - summary
      - claims
      - methods
      - evidence
expansion_hint:
  recommended: [work:1, work:4]
next_cursor: ...
```

## Tool contracts

Tool inputs and outputs should:

- use object roots
- use explicit enums
- avoid unnecessary union/combinator complexity
- keep optional fields truly optional/nullable according to target-client constraints
- return stable error codes
- support cursors for large collections
- enforce limits server-side
- expose cost/size hints when useful

## Provider neutrality

Agent callers should not need to know whether synthesis/extraction used Anthropic, OpenAI, local inference, or no LLM at all.

When a model is relevant to provenance, return a normalized model execution record rather than provider-specific response payloads.

## Agent Skills

Skills describe workflows and decision rules; they should not become an alternate business-logic implementation.

A portable skill may tell an agent:

1. search manifests first
2. rank candidate claims
3. expand only the strongest candidates
4. verify claims used in the answer
5. cite stable evidence IDs

The actual search/verification happens through platform services.

## Human and agent parity

Anything an agent can inspect should ideally be representable through a human-facing CLI/API/UI eventually. Avoid hidden "agent magic" that cannot be audited.

## Write boundaries

Read and write operations must be clearly distinguished.

Examples of writes:

- create workspace
- change inclusion decision
- approve identity merge
- record human verification
- run extraction that persists derived objects
- create synthesis/report snapshot

High-impact writes should support idempotency and audit records.

## Agent-to-code handoff

For coding agents, expose research implementation packages rather than free-form prose when possible.

Conceptual object:

```yaml
kind: implementation_candidate
source_claims:
  - claim:...
method: hierarchical_bayesian_regression
inputs:
  - days_rest
  - prior_pitch_count
required_data:
  - game_start_time
  - pitcher_game_log
validation:
  temporal_split_required: true
metrics:
  - log_loss
  - brier_score
references:
  - evidence:...
```

A Codex/Claude skill can then map this structured candidate to a target repository/database schema.

## Context persistence

Agents should be able to persist server-side handles to:

- saved searches
- result collections
- context packages
- snapshots

This avoids repeatedly reconstructing long intermediate state in model context.

## Error model

Errors should be actionable and structured:

```yaml
code: RIGHTS_FULLTEXT_UNAVAILABLE
message: Full text is not available under the configured acquisition policy.
recoverable: true
next_actions:
  - use_metadata_only
  - provide_user_artifact
```

The server should fail closed on authorization/rights uncertainty rather than silently broadening access.
