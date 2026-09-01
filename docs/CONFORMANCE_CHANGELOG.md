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
