# Development Guide

## Current stage

Tarkka has moved beyond the documentation-only foundation. The core local ingestion kernel and the first scholarly-discovery slice are implemented. Development should now preserve existing contracts while completing scholarly identity/enrichment and then moving into structured research extraction.

Read `AGENTS.md` before substantial changes. It is the shared coding-agent instruction file for Claude, Codex, and other repository-aware agents. `CLAUDE.md` adds Claude-specific context-loading guidance without duplicating the shared rules.

## Engineering goals

- Python-first core implementation
- strong typing
- explicit interfaces/protocols
- dependency inversion around external providers
- PostgreSQL as the reference metadata system of record
- deterministic/replayable pipelines
- structured logging and observability-ready boundaries
- robust network-free unit/contract tests
- local developer ergonomics
- no mandatory cloud services or LLMs for the base profile
- progressive disclosure for agent-facing data and tools

## Current Python baseline

The repository currently targets Python 3.11–3.13 in CI and uses:

- standard-library-first domain/application code where practical
- `psycopg` as an optional PostgreSQL integration
- optional Docling rich-document parsing behind `DocumentParser`
- `uv` for dependency resolution, project environments, and running development tools
- Hatchling as the standards-compliant package build backend
- pytest
- Ruff
- SQLFluff with the PostgreSQL dialect for new migration SQL
- strict mypy

Future dependencies should be adopted only when they materially improve the implementation and remain replaceable behind a narrow contract where appropriate.

For the selected PostgreSQL driver, migration, ORM, validation, and pooling approach, read
`docs/POSTGRESQL_PERSISTENCE.md`.

## Development environment

Use the committed `uv.lock` and the development dependency group:

```bash
uv sync --frozen --group dev
```

Run tools through the project environment:

```bash
uv run --no-sync ruff check .
uv run --no-sync mypy
uv run --no-sync sqlfluff lint migrations
uv run --no-sync pytest -m "not external"
```

When dependency declarations change intentionally, regenerate the lockfile with `uv lock`, review the dependency diff, and commit `pyproject.toml` and `uv.lock` together. Do not hand-edit `uv.lock`.

Development-only tools belong in the `dev` dependency group. Runtime dependencies belong in `[project.dependencies]` or narrowly scoped optional extras. Do not maintain parallel development requirements files or add test/lint tooling to runtime package metadata.

## Package layout

The implementation namespace is stable:

```text
src/tarkka/
  domain/
  application/
  ports/
  infrastructure/
    discovery/
    storage/
    postgres/
  interfaces/
```

As additional stages arrive, add focused modules such as extraction, retrieval, reporting, API, or MCP only when the corresponding application contracts exist. Do not create speculative empty framework layers.

Keep domain models separate from provider, parser, database, transport, CLI, and model-vendor details.

## Package-development conventions

Keep package metadata portable and standards-based. `uv` manages development and resolution; it does not replace the configured PEP 517 build backend.

- Preserve the `src/` layout and explicit `tarkka` package namespace.
- Keep optional integrations import-safe when their extras are not installed.
- Avoid runtime dependency on linters, test frameworks, build orchestration, or CI-only packages.
- Keep the CLI entry point in `[project.scripts]` thin and route behavior through application services.
- Treat changes to `requires-python`, extras, public imports, CLI behavior, and persisted schemas as compatibility changes.
- Build/release automation should consume committed metadata and lock state rather than maintaining a second dependency definition.

## Configuration

Target precedence:

```text
defaults < config file < environment < CLI/runtime override
```

Machine-facing naming:

- Python package: `tarkka`
- CLI: `tarkka`
- environment prefix: `TARKKA_`
- future configuration files: prefer `tarkka.*`

Secrets belong in environment/secret providers, not ordinary project manifests.

## Error model

Use typed application/domain errors with actionable interface messages.

Distinguish at least:

- invalid user input
- provider unavailable
- rate limited
- authentication required
- rights/policy denied
- unsupported artifact
- parse failure
- extraction failure
- verification uncertainty
- persistence/infrastructure failure

External provider data is untrusted. Validate at adapter boundaries and preserve failure context without leaking secrets.

## Logging

Structured logs should eventually include useful correlation identifiers such as workspace ID, run/snapshot ID, provider, work/artifact ID, stage, duration, and outcome.

Do not log full private source contents, API keys, signed URLs, or other secrets by default.

## Testing strategy

### Unit tests

- domain invariants
- identity/identifier normalization
- provider selection and result budgeting
- retry/cursor behavior
- rights/policy logic as it is introduced
- extraction contract validation in Phase 3

### Contract tests

Every replaceable parser/provider/store interface should gain shared behavior tests where practical.

### Integration tests

- PostgreSQL repositories and migrations
- artifact storage
- provider fixture normalization
- Docling adapter integration

### End-to-end tests

Use small deterministic corpora and fixture transports. Normal CI must not depend on live external scholarly APIs.

Existing golden flows include:

```text
local file
 -> SHA-256 artifact
 -> acquisition provenance
 -> normalized document
 -> section/passage
 -> compact manifest
 -> retrieve on demand
```

and:

```text
research query
 -> provider selection
 -> provider result pages
 -> SearchSnapshot
 -> DOI-first identity grouping
```

## Reproducibility

Research workflows should preserve versions, parameters, provider selections, cursors, timestamps, and source identities when those details affect later interpretation.

SearchSnapshots and raw artifacts are audit/reproducibility boundaries. Do not silently mutate historical records that are documented as append-only/immutable.

## Database migrations

Treat migrations as append-only historical artifacts after merge/release. Avoid rewriting published migration history.

The existing SQL files are authoritative. A future explicit Tarkka migration runner will record
applied versions and checksums; application startup must never run migrations implicitly.

Migration design should preserve:

- referential integrity
- explicit uniqueness
- version/time metadata
- common retrieval paths
- provenance
- conflicting source observations
- append-only guarantees where promised

SQLFluff was adopted after migrations `0001`–`0006`; those historical files are baselined in `.sqlfluffignore` rather than rewritten. Every new migration must pass the configured PostgreSQL SQLFluff rules before merge.

## Performance philosophy

Optimize after measuring, except where a boundary would make efficient operation impossible.

Measure over time:

- documents/minute
- parser latency
- discovery latency per provider
- provider error/retry rates
- deduplication/identity match rates
- extraction latency/cost
- database/retrieval latency
- artifact deduplication rate
- agent context bytes/tokens per task

## Pull request expectations

Each nontrivial PR should state:

- problem and scope
- design/approach
- affected contracts
- tests/validation
- migration implications
- security/rights implications where relevant
- compatibility/failure behavior
- context/token impact for agent-facing changes

Address substantive review comments before merge, but verify reviewer claims against current upstream documentation instead of applying automated suggestions blindly.

## Dependency policy

Prefer mature external assets over unnecessary custom reimplementation, but adopt them behind replaceable boundaries when they are architectural choices.

For substantial dependencies, record:

- why needed
- license
- alternatives
- transitive/security impact
- external network/data behavior
- replacement boundary
- test strategy

## Definition of done

A feature is not done because the happy path runs. Include appropriate validation, explicit failure behavior, tests, docs, provenance/version metadata, migration behavior, and agent-context considerations.
