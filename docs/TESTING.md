# Testing Strategy

Tarkka treats testing as a cross-cutting architectural concern, not a final cleanup step.

The goals are to catch regressions early, localize failures to a subsystem or contract, preserve reproducibility, and keep external services optional.

## Test layers

### Unit

Small deterministic behavior with no network, database, model server, or filesystem dependency unless the filesystem itself is the unit under test.

Examples:

- identifier normalization
- batching arithmetic
- domain validation
- serializer helpers

### Contract

Tests for invariants at public/domain/port boundaries. These are especially important when implementations are replaceable.

Examples:

- `ExtractionBatch` evidence integrity
- provider/adapter output shape
- repository idempotency
- parser postconditions
- fail-closed validation

### Integration

Tests that compose multiple Tarkka components while remaining reproducible and usually offline.

Examples:

- normalized `Document` -> extractor -> repository
- discovery snapshot -> explicit work selection
- artifact -> parser -> document repository

### Regression

A focused test for every meaningful bug discovered in development or review. A regression test should reproduce the original failure before the fix and name the behavior being protected.

### Property-based

Hypothesis-generated inputs exercise invariants that are difficult to cover with hand-picked examples.

High-value candidates include:

- batching always makes progress
- every normalized passage appears in at least one request
- request limits are respected except for a deliberately atomic oversized passage
- identifier normalization is idempotent
- serializers round-trip valid domain objects
- pagination preserves ordering and bounds

### External

Network/model/database tests are opt-in and must be marked `external`. The default test suite must never require credentials, internet access, a model server, PostgreSQL, or another separately running service.

## Markers

Tarkka defines these pytest markers:

```text
unit
contract
integration
regression
property
external
```

Markers are descriptive rather than mutually exclusive. For example, a test may be both `regression` and `contract`.

`--strict-markers` is enabled so misspelled or undocumented markers fail immediately.

## Development environment

`uv` is the canonical project/development environment manager. Install a compatible uv release and synchronize the development group:

```bash
uv sync --group dev
```

Run repository tools through `uv run` so local execution uses the same declared environment as CI:

```bash
uv run ruff check .
uv run mypy
uv run sqlfluff lint migrations
uv run pytest -m "not external"
```

Do not install project tooling globally or maintain parallel `requirements-dev.txt` files. Development-only tools belong in the `dev` dependency group in `pyproject.toml`; runtime features belong in normal dependencies or explicit optional extras.

## Default validation

CI separates static quality checks from the Python compatibility matrix:

- Ruff, strict mypy, and SQLFluff run once on the primary CI interpreter.
- pytest runs on Python 3.11, 3.12, and 3.13.
- external tests remain opt-in.
- branch coverage is collected during the Python 3.13 test run rather than rerunning the suite in a separate coverage job.

SQL migrations are linted with SQLFluff using the PostgreSQL dialect configured in `pyproject.toml`.

The default suite must remain deterministic and network-free after dependency installation.

## Coverage

Coverage is a diagnostic, not a substitute for meaningful assertions.

CI records branch coverage, reports missing lines, and retains `coverage.xml` as a workflow artifact for later inspection. Tarkka initially measures coverage without enforcing an arbitrary repository-wide percentage. Once a stable baseline is known, thresholds can be introduced per critical subsystem rather than rewarding low-value tests merely to increase a global number.

High-risk contracts should aim for behavior coverage even when total repository coverage is lower.

## Failure localization

Tests should make failures easy to classify. Prefer focused files and assertions over giant end-to-end tests.

Suggested organization as the suite grows:

```text
tests/
    unit/
    contracts/
    integration/
    regression/
    properties/
    external/
    support/
```

Existing tests do not need to be moved all at once. Migrate them when the relevant subsystem is changed so reorganizing tests does not become a large unrelated refactor.

## Fixtures and factories

Shared object construction should move toward small typed factories in `tests/support/` rather than copy/pasted setup. Factories should expose only the fields a test needs to vary and produce valid domain objects by default.

Invalid-object tests should mutate one invariant at a time so the resulting failure identifies the broken contract.

## Bug workflow

For a meaningful bug:

1. reproduce it with the smallest focused test;
2. confirm the test fails for the expected reason;
3. implement the fix;
4. keep the test permanently as a regression guard;
5. add a broader property or contract test when the bug reveals a class of failures rather than one isolated case.

## Multimodal research artifacts

Figures, tables, equations, and images will use the same testing discipline when introduced:

- artifact identity and source location are deterministic facts;
- OCR/vision output is adapter output and must satisfy explicit contracts;
- interpreted values or conclusions remain separate from immutable source artifacts;
- native structured extraction and OCR/vision fallbacks require fixture-based comparison tests;
- external vision/model calls remain optional and are replaced by deterministic fixtures in normal CI.
