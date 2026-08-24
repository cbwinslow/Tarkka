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

Every replaceable port should grow a reusable contract suite so each implementation proves the same externally visible behavior.

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
- traversal state transitions preserve invariants
- evidence offsets are ordered and in bounds
- URI normalization is stable across equivalent spellings

### Security

Security tests exercise adversarial inputs and fail-closed boundaries. These should remain deterministic and run without outside services unless explicitly marked `external`.

High-value areas include:

- SSRF and DNS-rebinding boundaries
- redirect validation and ambiguous headers
- query-string and credential redaction
- path traversal
- malformed URLs and Unicode/IDNA edge cases
- IPv4/IPv6 classification
- untrusted parser/model output
- resource exhaustion and acquisition budgets

### Failure injection

I/O and persistence code must be tested under partial failure, not only happy-path success.

Examples:

- artifact write succeeds but observation write fails
- observation write succeeds but checkpoint completion fails
- retry resumes from a durable intermediate state
- model/provider response is malformed after partial work
- timeout occurs between two otherwise valid operations

Shared deterministic fault primitives belong in `tests/support/` so these scenarios are easy to reproduce consistently.

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
security
slow
external
```

Markers are descriptive rather than mutually exclusive. For example, an SSRF regression may be both `security` and `regression`.

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

Changed code should move toward a diff-coverage gate so new behavior is held to a stronger standard without encouraging low-value repository-wide coverage padding.

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
    security/
    external/
    support/
```

Existing tests do not need to be moved all at once. Migrate them when the relevant subsystem is changed so reorganizing tests does not become a large unrelated refactor.

## Shared test support

Shared object construction should move toward small typed factories in `tests/support/` rather than copy/pasted setup. Test support is maintained code and must be typed, deterministic, documented, and independently tested.

Current primitives include:

- `ManualClock` for deterministic elapsed-time and timeout tests;
- `RecordingSleeper` for wait behavior without real sleeps;
- `FaultPlan` for deterministic failure injection on selected calls.

Do not create a one-off clock, sleeper, or generic failure counter when an existing shared helper covers the behavior.

Factories should expose only the fields a test needs to vary and produce valid domain objects by default. Invalid-object tests should mutate one invariant at a time so the resulting failure identifies the broken contract.

## Durable-state testing

Every durable record should have serialization round-trip coverage. Persistence adapters should additionally test:

- idempotent writes where the contract requires them;
- corrupted or malformed stored data;
- interrupted writes and restart recovery;
- compatibility when durable schemas evolve;
- deterministic identity after reload.

The authoritative inventory of Tarkka's current persistence surfaces and their executable coverage is maintained in [`DURABLE_STATE_TEST_MATRIX.md`](DURABLE_STATE_TEST_MATRIX.md). Update that matrix whenever a new durable repository, log, or schema-versioned format is introduced.

When migrations or durable formats are introduced, compatibility tests should protect upgrades rather than relying on manual inspection.

## Bug workflow

For a meaningful bug:

1. reproduce it with the smallest focused test;
2. confirm the test fails for the expected reason;
3. implement the fix;
4. keep the test permanently as a regression guard;
5. add a broader property or contract test when the bug reveals a class of failures rather than one isolated case.

## Mutation testing

Tarkka uses targeted mutation testing as a scheduled/manual quality layer for high-risk pure domain logic. It is intentionally separate from ordinary pull-request CI so expensive mutation runs cannot become a routine development bottleneck.

The pinned baseline tool is `mutmut==3.7.0`. It is resolved ephemerally through `uv` rather than installed into the normal development group:

```bash
rm -rf mutants
uv run --with mutmut==3.7.0 mutmut run
uv run --with mutmut==3.7.0 mutmut results
```

The exact tool pin and command are recorded in `pyproject.toml`, along with mutmut's mutation scope and focused pytest selection. The initial scope is deliberately small:

- `src/tarkka/domain/resource_acquisition.py`
- `src/tarkka/domain/traversal.py`

These modules are deterministic, security/reliability-sensitive, and already have focused unit/property/state-machine coverage. Adapter-heavy, generated, network-backed, and persistence-heavy modules are excluded until mutation results would provide a useful signal rather than noise.

Mutation testing currently establishes a baseline; it does **not** enforce a mutation-score threshold. Review surviving mutants individually:

1. if a survivor represents meaningful behavior, add or strengthen the smallest focused test that kills it;
2. if it is equivalent or otherwise non-actionable, document that conclusion in the relevant issue/PR rather than padding the score with artificial assertions;
3. keep the mutation scope explicit and grow it only when the target module's deterministic tests are mature.

The `Mutation Testing` GitHub Actions workflow runs weekly and can also be dispatched manually. It retains the mutmut results and working state for later inspection. Pull requests that change the mutation configuration validate that the pinned mutmut CLI resolves, but do not run the expensive mutation corpus.

## Multimodal research artifacts

Figures, tables, equations, and images will use the same testing discipline when introduced:

- artifact identity and source location are deterministic facts;
- OCR/vision output is adapter output and must satisfy explicit contracts;
- interpreted values or conclusions remain separate from immutable source artifacts;
- native structured extraction and OCR/vision fallbacks require fixture-based comparison tests;
- external vision/model calls remain optional and are replaced by deterministic fixtures in normal CI.

## Review checklist

Before merging behavior changes, verify the relevant items below:

- happy path covered;
- invalid input covered;
- important boundary values covered;
- persistence round trip covered when durable state changes;
- failure, retry, and interruption covered when I/O is involved;
- security and provenance impact considered;
- deterministic IDs or ordering tested when required;
- replaceable adapter behavior covered by a reusable contract where appropriate;
- regression test added for every bug fixed.

See issue #60 for the completed testing-framework foundation and focused follow-up issues for remaining improvements.
