# Generic acquisition contract

Tarkka's acquisition boundary answers one narrow question:

> Which adapter can safely obtain this source, and what bytes did it actually write?

It deliberately does **not** decide canonical research identity, parser selection, web cleaning,
or extraction semantics. Those remain separate layers.

## Candidate is not Artifact identity

`ArtifactCandidate` is a transport-neutral source locator. It contains an absolute URI and may
carry media type, filename, expected-size, or small string metadata hints.

Those values are routing hints only. They are not proof of content format or identity.
Canonical `Artifact` identity remains content-derived after bytes are preserved and hashed.

Examples of candidate URI schemes include `file:`, `http:`, `https:`, provider-defined schemes,
or connector-defined schemes such as an upload/object-store handle. The public contract does not
contain a provider or format allowlist.

When a candidate or receipt exposes a `filename`, it must be one safe filename component on both
POSIX and Windows. Path separators, traversal components, NULs, and blank names are rejected.
Adapters may preserve a source-native unsafe/raw filename separately in `SourceObservation`
provenance, but Tarkka must not let it become an implicit filesystem path.

Large or source-native provider records do not belong in candidate metadata. Preserve them as a
`SourceObservation` or immutable Artifact and reference them from canonical provenance.

Candidate and receipt metadata are deliberately small: at most 32 items, with keys no longer than
128 characters and string values no longer than 4096 characters. These public limits are exposed
as `MAX_ACQUISITION_METADATA_ITEMS`, `MAX_ACQUISITION_METADATA_KEY_CHARS`, and
`MAX_ACQUISITION_METADATA_VALUE_CHARS` so adapters can validate or trim routing metadata before
constructing the contract objects.

## Side-effect-free assessment

An `ArtifactAcquirer` exposes a `CapabilityManifest` and two operations:

```python
class ArtifactAcquirer(Protocol):
    @property
    def manifest(self) -> CapabilityManifest: ...

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision: ...

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact: ...
```

External adapters satisfy this protocol structurally. They do not inherit a Tarkka base class.

`assess()` must not retrieve or persist source content. It reports one of four states:

- `supported` — the adapter considers the candidate eligible for an acquisition attempt;
- `unsupported` — this adapter cannot handle the candidate;
- `policy_denied` — rights, authorization, or configured policy forbids acquisition;
- `unavailable` — the source/capability is currently not technically available for this adapter.

Every non-supported decision carries a non-blank reason. A supported assessment is not a promise
that the later operation will succeed: availability, authorization, remote state, or policy can
change between assessment and acquisition.

`assess_acquisition_adapters()` filters only adapters advertising `Capability.ACQUIRE` and returns
their assessments in caller-declared order. It does not choose a winner. Ranking, policy, and
tie-breaking belong to orchestration rather than the port contract.

## Stream into a caller-owned sink

`acquire()` writes bytes into a caller-owned binary sink instead of returning the complete payload
as `bytes`. This keeps the boundary usable for large local files, HTTP downloads, object stores,
structured-provider exports, connector bridges, and future staged persistence without making
whole-payload memory materialization part of the API.

The caller owns the sink lifecycle. An adapter must not close a sink it did not open.

If acquisition fails after writing partial content, the caller must discard that partial sink.
Tarkka must not publish or record it as a canonical Artifact.

## Success receipt

`AcquiredArtifact` is a receipt for the bytes written by the adapter. It records:

- requested and final URI;
- exact byte count;
- lowercase SHA-256 digest;
- optional media type and filename;
- explicit redirect hops when any redirects occurred;
- small string metadata useful for acquisition provenance/routing.

The receipt itself is not a canonical `Artifact`. The application layer must commit the staged
bytes to an `ArtifactStore`, independently verify that the committed size and digest match the
receipt, and only then record canonical acquisition/provenance state.

`requested_uri`, `final_uri`, and `redirect_chain` are separate observations. A transport may
normalize URI spelling without redirecting, so a changed `final_uri` does not by itself imply a
redirect. When redirect hops are recorded, the last hop must equal `final_uri`; a chain may also
legitimately return to the original requested URI.

## Failure model

Runtime failures use `AcquisitionError` with a stable `AcquisitionFailureKind`:

- `unsupported` — candidate support changed or could not be honored;
- `policy_denied` — acquisition is forbidden by rights/auth/policy;
- `transient` — a bounded retry may be appropriate;
- `unavailable` — the requested source/capability cannot currently be obtained.

Only `transient` is generically retryable. The orchestration layer may apply stricter source- or
policy-specific limits, but it must not automatically retry terminal failure classes.

## What this slice intentionally does not do

This contract does not yet add:

- plugin loading or entry-point discovery;
- HTTP/local/object-store reference adapters using this new port;
- content sniffing or parser support scoring;
- web cleaning/extraction selection;
- resumable bulk-ingestion checkpoints, backpressure, or concurrency;
- research-plan/tool orchestration.

Those are separate #275 child slices. Keeping them separate prevents an early adapter contract
from freezing implementation details that should remain replaceable.

The preservation rule remains unchanged throughout the larger ingestion pipeline:

> preserve native structure first; normalize second; infer last.
