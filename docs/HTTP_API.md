# HTTP / OpenAPI agent interface

Tarkka's HTTP surface is a thin read-only ASGI adapter over the same application
contracts used by CLI and MCP. It does not own research semantics or persistence.

## Application object

The dependency-free ASGI application is available at:

```text
tarkka.interfaces.http_api:app
```

Use any standards-compliant ASGI server. Keep public deployment decisions outside
Tarkka's core package; for local development, bind the server to loopback unless you
have deliberately configured authentication and network policy around it.

## Initial endpoints

```text
GET /v1/capabilities
GET /v1/operations/{operation_id}
GET /v1/claims/{claim_id}/lineage
GET /openapi.json
```

Claim lineage accepts the same two independent bounded pages as MCP:

```text
offset=0&limit=20&evidence_offset=0&evidence_limit=20
```

`offset` / `limit` page verification assessments. `evidence_offset` /
`evidence_limit` page original Claim evidence before source resolution.

## Contract ownership

The HTTP adapter reuses:

- `ClaimLineageService` for research semantics;
- `claim_lineage_view` through the shared agent response helper;
- `ResearchOperationSchema` metadata for OpenAPI pagination bounds;
- the stable Claim-lineage machine problem vocabulary.

This means HTTP clients receive the same semantic Claim lineage as `tarkka why` and
MCP `claim_lineage`, with HTTP status codes added only as transport metadata.

## Error mapping

Semantic machine codes remain stable across transports. HTTP maps them as follows:

- typed request/pagination failures: `400`;
- missing Claim/evidence/source handles: `404`;
- persisted lineage contradictions: `409`;
- bounded responses that still exceed the response ceiling: `413`;
- backend/configuration/persisted-state availability failures: `503`.

Unexpected unmapped machine errors fail closed as `500`.

## Security defaults

The first HTTP slice is GET-only and does not emit permissive CORS headers. JSON
responses include `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
Query parsing is closed-world and bounded before integer conversion. Claim-lineage
inspection remains local/offline: it performs no hidden model, provider, or network
calls.
