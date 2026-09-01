# Conformance API versioning policy

Tarkka's adapter conformance API has its own compatibility major, exposed as
`tarkka.conformance.CONFORMANCE_API_VERSION`.

The current major is `1`.

## Compatibility promise

Within one conformance major, Tarkka may add new contract classes or new optional
assertion helpers, but existing published imports and assertion signatures remain
available. A new major is required before Tarkka removes or renames a published
contract, makes an existing assertion require new positional inputs, or changes
an assertion so it no longer represents the corresponding public port contract.

This version is intentionally independent from:

- Tarkka's package release number;
- a plugin's own semantic version;
- provider/parser/model versions recorded in research provenance.

A plugin should record the conformance major it validates in CI. It may reject a
different major before running expensive integration tests.

## Suggested plugin guard

```python
from tarkka.conformance import CONFORMANCE_API_VERSION

SUPPORTED_CONFORMANCE_MAJOR = "1"

if CONFORMANCE_API_VERSION != SUPPORTED_CONFORMANCE_MAJOR:
    raise RuntimeError(
        "plugin has not been validated against Tarkka conformance API "
        f"{CONFORMANCE_API_VERSION}"
    )
```

The guard is intentionally explicit rather than hidden in plugin discovery. A
future plugin loader can consume compatibility metadata after multiple external
plugins exercise the contract; this first kit does not add speculative registry
or entry-point machinery.
