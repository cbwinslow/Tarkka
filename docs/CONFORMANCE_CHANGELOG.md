# Conformance API changelog

## API 1

Initial public adapter conformance surface.

Published contracts:

- `ArtifactStoreContract`
- `ResearchRepositoryContract`
- `ExtractionRepositoryContract`
- `CitationRepositoryContract`
- `SourceObservationRepositoryContract`
- `WorkRepositoryContract`
- `HostResolverContract`
- `HttpTransportContract`

The API 1 implementation was promoted from Tarkka's existing shared reference
adapter contracts. Tarkka's own JSON, PostgreSQL, local artifact, resolver, and
HTTP transport suites consume this same public package.

Publication hardening completed before the API 1 merge:

- `ArtifactStoreContract.assert_round_trip` verifies that `put_file` and
  `put_bytes` produce identical content identity and storage keys for identical
  bytes, and verifies `read_bytes_by_sha256` recovery.
- `HttpTransportContract.assert_body_cap_is_explicit` accepts either the
  port-defined capped response with `limit_exceeded=True` or an adapter's
  explicitly advertised oversized-response exception via the optional
  `overflow_error` argument. Unadvertised exceptions still fail closed.
