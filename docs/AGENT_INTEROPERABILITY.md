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
- `limit`: verification-assessment page size, `0..100`.

The tool is read-only, non-destructive, idempotent, closed-world, local/offline, and
does not invoke a model, provider, or network source.

Its payload is the same transport-neutral lineage view used by `tarkka why`. It
contains Claim extraction provenance, exact evidence locators, normalized Document
identity, immutable Artifact identity/hash, bounded verification assessments, and
citation context where present.

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

Unexpected programming errors are not converted into ordinary machine problems.

## Output bounds

Verification assessments are paginated by the application service. MCP also applies
the same estimated-token ceiling used by bounded context expansion. If the complete
lineage view would exceed that ceiling, the tool fails closed with
`content_too_large` rather than returning an unexpectedly large agent payload.

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
