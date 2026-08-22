# HTTP observations and content routing

Issue #28 separates transport acquisition from research semantics.

## Transport preservation

`HttpResponseSnapshot` preserves one HTTP response as immutable transport facts:

- normalized requested URI;
- normalized final URI;
- normalized redirect chain;
- status code;
- a safe allowlist of normalized response headers;
- discovered depth;
- response observation time.

Response bytes remain in Tarkka's immutable artifact store. The snapshot projects into the existing `SourceObservation` envelope with `basis=native` and a `native_artifact_id`; it does not create or mutate a canonical `Work`.

### Secret-retention policy

Durable transport observations must never become a secret store. URI userinfo is removed and common credential-bearing query parameters are replaced with `[REDACTED]` before the snapshot is retained. Only a small response-header allowlist is preserved; authentication headers and `Set-Cookie` are excluded. The same sanitized representation is used for stable-ID construction, so changing only a redacted secret does not produce a new observation identity.

The stable observation ID is derived from the immutable artifact ID plus sanitized stable transport facts. A repeated observation of the same response can therefore be persisted idempotently while `observed_at` remains first-seen metadata in the local observation repository.

## Media routing

`ContentRouter` consumes `CapabilityManifest` records rather than crawler-specific conditionals. Parser media types are validated when the router is constructed. For a normalized media type the router returns all adapters that:

- are `AdapterKind.PARSER`;
- advertise `Capability.PARSE`;
- advertise the acquired media type.

Candidates are deterministic and sorted by adapter name. If no parser advertises support, the route is explicitly `artifact_only`; the acquired bytes remain preserved instead of being discarded or forced through an unsuitable parser.

Adding support for a new format therefore requires a parser/adapter manifest, not a crawler modification.

### Routing example

```python
from tarkka.application.content_routing import ContentRouter
from tarkka.domain.source_observations import AdapterKind, Capability, CapabilityManifest

html = CapabilityManifest(
    adapter_name="semantic-html",
    adapter_kind=AdapterKind.PARSER,
    version="1",
    capabilities=frozenset({Capability.PARSE}),
    media_types=frozenset({"text/html"}),
)
router = ContentRouter((html,))

supported = router.route("text/html; charset=utf-8")
assert supported.parser_adapters == ("semantic-html",)
assert not supported.artifact_only

unsupported = router.route("application/x-new-format")
assert unsupported.parser_adapters == ()
assert unsupported.artifact_only
```

If multiple parser manifests advertise the same media type, `parser_adapters` is sorted by adapter name so routing results remain deterministic.

Run the focused checks with:

```bash
uv run --no-sync pytest tests/test_http_observations.py
```

If routing is unexpected, inspect the adapter's `CapabilityManifest`: it must be a parser, advertise `Capability.PARSE`, and provide a valid exact `type/subtype` media type. Then compare that normalized value with `ContentRouteDecision.media_type`.

## Boundary

This slice intentionally does **not** perform DNS resolution, HTTP requests, redirect following, crawling, robots evaluation, content sniffing, link extraction, parser invocation, or Work identity resolution. The HTTP adapter must first obey `ResourceAcquisitionPolicy`, then persist the returned artifact and sanitized transport observation. Later orchestration can pass the observed media type to `ContentRouter` and invoke the selected parser through application-layer composition.
