# HTTP acquisition

Tarkka's HTTP acquisition path keeps network mechanics separate from research semantics.

## Flow

1. Select a queued `TraversalTarget` from a `TraversalCheckpoint`.
2. Validate the URI against `ResourceAcquisitionPolicy`.
3. Persist the target as in-progress before network activity.
4. Resolve the hostname immediately before each connection.
5. Require the chosen resolved IP to pass `allows_resolved_address()`.
6. Connect through `PinnedHttpTransport`, which uses that exact IP and never follows redirects.
7. Checkpoint response bytes immediately.
8. Revalidate, re-resolve, charge, and checkpoint every redirect hop.
9. Persist the final body in the content-addressed artifact store.
10. Project sanitized transport facts into `HttpResponseSnapshot` / `SourceObservation`.
11. Mark the traversal target complete.

## Security and provenance rules

- Domain/scheme policy is checked before DNS and before every redirect.
- The actual TCP connection is pinned to an already-approved resolved address. The transport must not perform a second uncontrolled DNS lookup.
- HTTPS still verifies certificates and sends SNI for the URI hostname, not the resolved IP.
- Redirects are disabled in the transport and bounded by `max_redirects` in the policy.
- Response bytes are bounded by the remaining global byte budget. A transport that violates its advertised cap is detected; consumed bytes are still charged before the target fails.
- Request and response usage is checkpointed between hops so a restart cannot silently refund completed network work.
- Transport/resolver exception text is not copied into durable checkpoint errors.

## Signed and secret-bearing URLs

The durable traversal URI is sanitized by `normalize_http_uri()`. When a resource requires a signed query URL, the caller may provide the original URL transiently through `request_uri`.

The service requires the raw URL's sanitized normalization to equal the queued target URI. The raw URL may be passed to the network transport, but it is not written to:

- traversal checkpoints,
- artifact `source_uri`,
- HTTP observations,
- redirect provenance, or
- durable failure reasons.

This preserves acquisition capability without turning signed credentials into research data.

## Persistence boundary

`HttpAcquisitionService` requires three durable stores:

- `ArtifactStore`,
- `SourceObservationRepository`, and
- `TraversalCheckpointRepository`.

If checkpoint persistence fails before a network step, acquisition stops rather than continuing with state that cannot be resumed safely.

## Transport boundary

`SystemHostResolver` and `PinnedHttpTransport` provide a stdlib implementation. The resolver and transport remain ports so tests and alternative networking stacks can be injected without changing traversal, provenance, or research-domain code.

The transport currently performs GET requests only and intentionally does not implement cookies, authentication sessions, proxies, JavaScript execution, or automatic retries. Those behaviors require explicit policy and provenance contracts before they are added.
