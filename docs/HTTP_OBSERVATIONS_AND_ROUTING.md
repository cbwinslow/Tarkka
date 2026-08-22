# HTTP observations and content routing

Issue #28 separates transport acquisition from research semantics.

## Transport preservation

`HttpResponseSnapshot` preserves one HTTP response as immutable transport facts:

- requested URI;
- final URI;
- redirect chain;
- status code;
- normalized response headers;
- discovered depth;
- response observation time.

Response bytes remain in Tarkka's immutable artifact store. The snapshot projects into the existing `SourceObservation` envelope with `basis=native` and a `native_artifact_id`; it does not create or mutate a canonical `Work`.

The stable observation ID is derived from the immutable artifact ID plus stable transport facts. A repeated observation of the same response can therefore be persisted idempotently while `observed_at` remains first-seen metadata in the local observation repository.

## Media routing

`ContentRouter` consumes `CapabilityManifest` records rather than crawler-specific conditionals. For a normalized media type it returns all parser adapters that:

- are `AdapterKind.PARSER`;
- advertise `Capability.PARSE`;
- advertise the acquired media type.

Candidates are deterministic and sorted by adapter name. If no parser advertises support, the route is explicitly `artifact_only`; the acquired bytes remain preserved instead of being discarded or forced through an unsuitable parser.

Adding support for a new format therefore requires a parser/adapter manifest, not a crawler modification.

## Boundary

This slice intentionally does **not** perform DNS resolution, HTTP requests, redirect following, crawling, robots evaluation, content sniffing, link extraction, parser invocation, or Work identity resolution. The HTTP adapter must first obey `ResourceAcquisitionPolicy`, then persist the returned artifact and transport observation. Later orchestration can pass the observed media type to `ContentRouter` and invoke the selected parser through application-layer composition.
