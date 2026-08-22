# Resource acquisition policy

Tarkka separates network acquisition policy from crawler, parser, and research semantics. The acquisition layer decides whether a resource may be contacted and whether sufficient budget remains; it does not create or resolve canonical Works.

## Fail-closed scope

`ResourceAcquisitionPolicy` requires an explicit domain allowlist. An empty allowlist denies every network target. HTTP and HTTPS are the default eligible URI schemes, but a URI is not eligible unless its normalized DNS hostname matches an allowed domain or subdomain.

URI checks reject embedded user credentials and IP-literal hosts. Unicode domains are normalized through IDNA before comparison, so scope decisions use one canonical hostname representation.

URI validation alone is not enough for SSRF protection because DNS can change between validation and connection. The eventual HTTP adapter must resolve the hostname and call `allows_resolved_address` immediately before connecting. By default that check permits only globally routable IP addresses and rejects private, loopback, link-local, reserved, multicast, and unspecified targets. Private-network acquisition requires an explicit `allow_private_addresses=True` policy.

## Hard budgets

The policy defines explicit bounds for:

- crawl/discovery depth;
- total requests;
- total response bytes;
- retries per resource;
- elapsed wall-clock time;
- minimum interval between requests;
- URI schemes;
- DNS domains.

`AcquisitionBudgetState` is immutable counter state used to decide whether another request may be attempted. The orchestration layer owns updating those counters from actual request/response observations; adapters must not silently reset or bypass them.

Unknown rate-limit timing fails closed once at least one request has already been made and a positive minimum request interval is configured.

## Architecture boundary

This policy performs no DNS lookup, HTTP request, robots evaluation, parsing, routing, or Work identity resolution. Those behaviors belong to later adapters/application services. Network code must consume this policy rather than duplicating scope and budget rules independently.

This is the policy foundation for issue #28's bounded pipeline:

`URL discovery -> HTTP observation -> content identification -> resource-link discovery -> routing`

Later slices should preserve immutable HTTP observations and reuse the existing `SourceObservation` / `ResourceLinkObservation` contracts rather than introducing a parallel provenance model.
