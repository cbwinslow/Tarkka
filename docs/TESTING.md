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

### Managed PostgreSQL integration tests

`pytest-postgresql` is a development-only dependency. It connects to an existing PostgreSQL
server, migrates a dedicated template database, then gives each marked test a disposable clone.
It never uses `TARKKA_DATABASE_URL`, which is reserved for the application database.

Local defaults target the PostgreSQL 17 Unix socket at `/var/run/postgresql` on port `5434` as
the local development role. Override only the test endpoint when necessary:

```bash
export TARKKA_TEST_DATABASE_URL='postgresql://test_role@localhost:5434/postgres'
uv run pytest tests/test_postgres_native_ingest.py -m 'integration and external'
```

The test role must be allowed to create and drop databases. Keep application/production data in a
separate database (for example `tarkka`) and never point `TARKKA_TEST_DATABASE_URL` at it.

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

The MCP interface is an optional runtime extra. CI installs it explicitly with `uv sync --frozen --group dev --extra mcp` so the MCP contract is exercised on every pull request. Base environments without the extra may collect the rest of the deterministic suite; MCP-specific tests skip at module collection rather than turning an unrelated test profile into an import failure.

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

Coverage is a quality gate and diagnostic, not a substitute for meaningful assertions. A line or branch counts only when the test protects observable behavior, an invariant, a failure mode, or a contract that matters.

As of 2026-08-27, Tarkka's historical repository-wide branch-coverage baseline is approximately 86%. That legacy baseline is explicit coverage debt; it is not permission for new uncovered code and must not be hidden with exclusions or low-value assertions.

CI enforces a ratchet with two complementary rules:

1. every added or modified executable source line in a pull request must have **100% changed-line coverage**;
2. critical subsystems can be promoted to **100% branch coverage** as a whole, after which the subsystem gate prevents regression.

The Phase 5 agent-serving surface is the first subsystem promoted under this policy. Its capability discovery, bounded document retrieval, saved context-package domain/application/persistence paths, MCP interface, telemetry, and related ports are enforced at 100% branch coverage in CI.

Repository-wide 100% branch coverage remains the target. Raise the baseline deliberately by closing one coherent subsystem at a time, prioritizing security boundaries, durable state, interfaces, and complex control flow. Do not weaken an existing subsystem gate to make unrelated work pass.

CI reports missing lines and retains `coverage.xml` for inspection. When a coverage gate fails, add the smallest behavior-focused tests that exercise the missing contract or branch. If a branch is genuinely unreachable or represents dead code, prefer simplifying/removing the production branch rather than excluding it solely to inflate the score.

Coverage alone is insufficient. Mutation testing, property tests, failure injection, contract suites, security regression tests, and review remain independent signals of test quality.

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

The exact tool pin and command are recorded in `pyproject.toml`, along with mutmut's mutation scope and focused pytest selection. The current baseline deliberately targets persistence-sensitive identity logic with stable external contracts:

- `src/tarkka/domain/identifiers.py`
- `src/tarkka/infrastructure/storage/parser_identity.py`

The first verified baseline generated 52 mutants: 45 were killed, 6 survived, and 1 timed out. The six survivors only alter diagnostic `ValueError` message text, which is not part of the normalization contract. The timeout replaces DOI prefix removal with suffix removal and loops rather than surviving behaviorally. All generated deterministic parser-UUID mutations are killed. No mutation-score threshold is enforced yet.

The original acquisition/traversal targets are intentionally deferred. `mutmut==3.7.0` cannot currently instrument their dataclass lifecycle reliably: dataclass-generated `__init__` frames invoke instrumented `__post_init__` code from filename `<string>`, which mutmut's trampoline attempts to resolve as a file under `mutants/`. Production validators must not gain tool-specific pragmas merely to accommodate that instrumentation edge case. Revisit those targets when mutmut can handle the lifecycle safely or when the domain exposes an equally clean tool-independent mutation seam.

Adapter-heavy, generated, network-backed, persistence-heavy, or high-noise modules remain excluded until mutation results would provide a useful signal rather than score churn. Broader exploratory runs against robots matching and model-research mapping produced substantially noisier survivor sets and are better handled as focused future mutation campaigns.

Mutation testing establishes a baseline; it does **not** enforce a mutation-score threshold. Review surviving mutants individually:

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
- regression test added for every bug fixed;
- changed executable lines are 100% covered;
- any subsystem already ratcheted to 100% branch coverage remains at 100%.

See issue #60 for the completed testing-framework foundation and focused follow-up issues for remaining improvements.
