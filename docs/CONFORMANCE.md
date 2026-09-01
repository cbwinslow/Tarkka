# Adapter conformance kit

Tarkka publishes its reusable adapter behavior checks as `tarkka.conformance`.
The same contracts are used by Tarkka's reference adapters, so third-party
adapters can validate against the behavior the core actually expects rather
than copying examples from the repository test tree.

## Public API

```python
from tarkka.conformance import (
    CONFORMANCE_API_VERSION,
    ArtifactStoreContract,
    CitationRepositoryContract,
    ExtractionRepositoryContract,
    HostResolverContract,
    HttpTransportContract,
    ResearchRepositoryContract,
    SourceObservationRepositoryContract,
    WorkRepositoryContract,
)
```

`CONFORMANCE_API_VERSION` is currently `"1"`.

The conformance package has no pytest dependency. Its contract methods are plain
Python assertions, so callers may run them from pytest, unittest, another test
runner, or a purpose-built plugin CI job.

## Minimal external adapter example

A third-party artifact store can reuse the same behavior checks as Tarkka's
local content-addressed store:

```python
from pathlib import Path

from my_plugin import MyArtifactStore
from tarkka.conformance import ArtifactStoreContract


def test_my_store_conforms(tmp_path: Path) -> None:
    store = MyArtifactStore(tmp_path / "objects")

    ArtifactStoreContract.assert_round_trip(
        store,
        tmp_path / "paper.txt",
        b"auditable research\n",
    )
    ArtifactStoreContract.assert_duplicate_write_is_idempotent(
        store,
        tmp_path / "first.txt",
        tmp_path / "second.txt",
        b"same immutable bytes\n",
    )
    ArtifactStoreContract.assert_missing_digest_is_absent(store)
    ArtifactStoreContract.assert_missing_source_fails(
        store,
        tmp_path / "missing.txt",
    )
```

The adapter remains responsible for constructing domain fixtures required by
repository contracts. This keeps conformance focused on public port behavior
rather than imposing a Tarkka-specific test framework or fixture loader.

## Published contracts

| Contract | Port behavior protected |
| --- | --- |
| `ArtifactStoreContract` | content identity, round trip, duplicate idempotency, missing-source behavior |
| `ResearchRepositoryContract` | Artifact/Document/manifest persistence and idempotent saves |
| `ExtractionRepositoryContract` | extraction/evidence round trip, filtering, idempotency, conflict failure |
| `CitationRepositoryContract` | citation graph persistence, resolution evolution, relation identity/atomicity/bounds |
| `SourceObservationRepositoryContract` | observation/link idempotency and immutable-conflict behavior |
| `WorkRepositoryContract` | Work identity, deterministic listing, evolution, transaction rollback/conflicts |
| `HostResolverContract` | canonical resolved addresses and input validation |
| `HttpTransportContract` | pinned-address requests, redirect refusal, explicit response-byte ceilings |

`HttpTransportContract` uses only a loopback standard-library HTTP server. It
does not contact an external host. `HostResolverContract.assert_valid_unique_addresses`
resolves the hostname supplied by the caller, so external plugin suites should
use an environment-appropriate deterministic hostname when network isolation is
required.

## Compatibility rules

The conformance API version is intentionally separate from an adapter's own
semantic version and from Tarkka's package release number.

- A change that removes or renames a published contract, changes a required
  method signature incompatibly, or redefines an existing assertion outside the
  corresponding Tarkka port contract requires a new conformance API major.
- New contract classes and additive assertion methods may be introduced within
  the same major when they do not invalidate existing callers.
- A plugin should record the conformance API major it tests against in its own
  package metadata or release notes.
- Passing the conformance suite means the tested behavior matches the selected
  Tarkka port contract. It does **not** make third-party plugin code trusted,
  sandboxed, or safe to grant arbitrary network/filesystem credentials.

When upgrading Tarkka, plugin CI should import `CONFORMANCE_API_VERSION` and fail
clearly if the plugin has not been validated against that major.

## Why this lives in `src/`

These contracts used to be private helpers under `tests/contracts/`. Publishing
them under `src/tarkka/conformance/` makes one implementation authoritative.
Tarkka's JSON, PostgreSQL, local artifact, resolver, and HTTP transport tests run
that same public code. Behavioral changes therefore cannot drift between
"internal" and "plugin" conformance suites.

## Scope

This first public kit covers adapters for which Tarkka already had mature shared
behavioral contracts. Parser, discovery-provider, model-provider, and plugin
registration conformance should be added only after their public contracts are
stable enough to test without freezing accidental implementation details.

See [`CONNECTOR_PLUGIN_SPEC.md`](CONNECTOR_PLUGIN_SPEC.md) for the broader plugin
architecture and security model.
