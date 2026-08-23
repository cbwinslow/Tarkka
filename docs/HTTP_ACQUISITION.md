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
9. Persist a `FINALIZING` checkpoint containing the expected artifact and observation identities.
10. Persist the final body in the content-addressed artifact store and save its source observation.
11. Mark the traversal target complete.

## Security and provenance rules

- Domain/scheme policy is checked before DNS and before every redirect.
- The actual TCP connection is pinned to an already-approved resolved address. The transport must not perform a second uncontrolled DNS lookup.
- HTTPS still verifies certificates and sends SNI for the URI hostname, not the resolved IP.
- Redirects are disabled in the transport and bounded by `max_redirects` in the policy.
- Response bytes are bounded by the remaining global byte budget. A transport that violates its advertised cap is detected; consumed bytes are still charged before the target fails.
- Request and response usage is checkpointed between hops so a restart cannot silently refund completed network work.
- DNS, connection, and response-body work are bounded by the remaining acquisition deadline.
- Transport/resolver exception text is not copied into durable checkpoint errors.

## Signed and secret-bearing URLs

The durable traversal URI is sanitized by `normalize_http_uri()`. Benign query values remain part of resource identity and can be acquired directly from the durable URI. If sanitization removes a credential value, the caller must provide the original URL transiently through `request_uri`.

The service requires the raw URL's sanitized normalization to equal the queued target URI. The raw URL may be passed to the network transport, but it is not written to:

- traversal checkpoints,
- artifact `source_uri`,
- HTTP observations,
- redirect provenance, or
- durable failure reasons.

This preserves acquisition capability without turning signed credentials into research data.

## Persistence boundary and recovery

`HttpAcquisitionService` requires three durable stores:

- `ArtifactStore`,
- `SourceObservationRepository`, and
- `TraversalCheckpointRepository`.

If checkpoint persistence fails before a network step, acquisition stops rather than continuing with state that cannot be resumed safely.

Before output persistence, the service writes a `FINALIZING` checkpoint containing the artifact digest and observation ID it expects to commit. `acquire()` accepts only `QUEUED` targets; a restarted `FINALIZING` target must be reconciled with `recover_finalization()` instead of being fetched again.

`recover_finalization()` reloads the authoritative durable checkpoint, verifies that the finalization identity has not changed, and performs no network I/O. If both expected outputs are durable and consistent, it completes the target. If one or both outputs are absent, it marks the target `FAILED` so normal retry policy can requeue it. If a durable observation conflicts with the expected artifact identity, recovery fails closed rather than overwriting the conflicting evidence.

## Transport boundary

`SystemHostResolver` and `PinnedHttpTransport` provide a stdlib implementation. The resolver and transport remain ports so tests and alternative networking stacks can be injected without changing traversal, provenance, or research-domain code.

The transport currently performs GET requests only and intentionally does not implement cookies, authentication sessions, proxies, JavaScript execution, or automatic retries. Those behaviors require explicit policy and provenance contracts before they are added.

## Debugging failures

The acquisition boundary separates failure classes so operators can tell whether network work, checkpoint durability, or output commit/recovery failed:

- `HttpAcquisitionError` — a started acquisition failed and was durably marked failed.
- `HttpAcquisitionCheckpointError` — checkpoint persistence failed before the service could safely continue.
- `HttpAcquisitionCommitError` — output finalization or recovery could not be completed safely.

Durable target error text intentionally records only a sanitized failure category rather than raw transport exception text. Inspect the live Python exception chain for operational detail, while treating the persisted checkpoint as the authoritative restart state.
