# Agent interoperability

Tarkka treats AI interoperability as a transport problem, not as a second research
implementation.

The stable dependency direction is:

```text
durable repositories
        |
        v
application services
        |
        +--> transport-neutral views + machine problems
                    |
                    +--> CLI
                    +--> MCP
                    +--> future REST/OpenAPI
```

No transport is allowed to reimplement provenance, evidence, identity, or persistence
semantics.

## Why MCP comes first

Model Context Protocol (MCP) gives an AI agent a discoverable tool surface. The agent
does not need to scrape terminal output or know Tarkka's Python internals.

Tarkka exposes a deliberately staged MCP contract:

1. `research_capabilities` returns compact semantic operation handles.
2. `research_operation_schema` expands the typed input contract for one selected
   operation.
3. A concrete MCP tool performs the selected bounded operation.

This keeps first-turn tool context small while allowing an agent to discover deeper
capabilities only when needed.

## Claim lineage

The semantic operation:

```text
research.claims.lineage
```

is implemented by `ClaimLineageService.inspect`.

The MCP tool:

```text
claim_lineage
```

accepts:

- `claim_id`: UUID or `claim:<uuid>` handle;
- `offset`: verification-assessment offset, `0..10000`;
- `limit`: verification-assessment page size, `0..100`;
- `evidence_offset`: original Claim-evidence offset, `0..10000`;
- `evidence_limit`: original Claim-evidence page size, `0..100`.

The two page controls are independent. An agent can inspect a small original-evidence
page without expanding every Evidence record attached to a Claim, while independently
paging verification assessments.

The tool is read-only, non-destructive, idempotent, closed-world, local/offline, and
does not invoke a model, provider, or network source.

Its payload is the same transport-neutral lineage view used by `tarkka why`. It
contains Claim extraction provenance, normalized Document identity, immutable Artifact
identity/hash, bounded original evidence, bounded verification assessments, and
citation context where present. `claim_evidence_page` reports `offset`, `limit`, and
`total` so clients can continue evidence expansion deterministically.

Resolved source metadata is included for every supported Evidence kind. Passage
evidence carries its exact span and text; Figure evidence carries source label,
caption, page, ordinal, and type; Table evidence carries source label, caption, page,
shape, ordinal, and exact cell range; Equation evidence carries source label, page,
ordinal, and preserved source text where available. This prevents Figure/Table/Equation
handles from becoming opaque dead ends for an agent.

## Stable machine errors

Expected Claim-lineage failures use semantic codes rather than requiring an agent to
parse exception text:

- `invalid_argument`
- `claim_not_found`
- `evidence_not_found`
- `extraction_run_not_found`
- `document_not_found`
- `artifact_not_found`
- `citation_repository_unavailable`
- `citation_context_not_found`
- `lineage_mismatch`
- `backend_unavailable`
- `content_too_large`

`invalid_argument` is reserved for typed request-boundary failures such as invalid
lineage pagination. Backend configuration failures and malformed persisted state are
reported as `backend_unavailable`; durable identity contradictions remain the distinct
`lineage_mismatch` class. Unexpected programming errors are not converted into ordinary
machine problems.

## Output bounds

Original Claim evidence and verification assessments are independently paginated by
the application service before source resolution. MCP then applies the same
estimated-token ceiling used by bounded context expansion. If a bounded lineage view
would still exceed that ceiling, the tool fails closed with `content_too_large` rather
than returning an unexpectedly large agent payload. Clients can retry with a smaller
`evidence_limit`, verification `limit`, or both.

Claim text itself remains one atomic semantic Claim datum rather than a hidden bulk
expansion. Original Evidence is the potentially high-cardinality collection and is
therefore explicitly paginated before it is resolved.

## Backend coherence

CLI and MCP construct Claim lineage through the same public runtime helper. JSON mode
uses only the local JSON catalogs; PostgreSQL mode uses only PostgreSQL repositories
created from one `PostgresSettings` object. Mixed durable-state reads are not allowed.

## Future REST/OpenAPI

REST/OpenAPI should be an additional adapter over the same three public pieces:

- `ClaimLineageService`
- the Claim-lineage view
- the Claim-lineage machine-problem vocabulary

The HTTP layer should not introduce another lineage schema, repository graph, or error
taxonomy. This keeps MCP, CLI, Python, and HTTP clients interoperable and makes
conformance testing possible.
