# Development Guide

## Current stage

The project is documentation-first. Implement the first vertical slice only after the foundation documents are reviewed.

## Engineering goals

- Python-first core implementation
- strong typing
- explicit interfaces/protocols
- dependency inversion around external providers
- PostgreSQL as reference system of record
- deterministic/replayable pipelines
- structured logging
- observability-ready code
- robust tests
- local developer ergonomics
- no mandatory cloud services for the base profile

## Proposed Python baseline

Exact package choices should be validated during implementation, but the initial stack should evaluate:

- Python 3.12+
- `uv` for environment/package management
- `pydantic` for boundary/config schemas where appropriate
- standard library dataclasses or focused domain types internally when they reduce coupling
- SQLAlchemy 2.x + Alembic, or carefully justified direct PostgreSQL tooling
- `psycopg` for PostgreSQL access where direct operations are useful
- FastAPI for REST only after application services exist
- Typer or Click for CLI
- pytest
- Ruff
- mypy or pyright
- structlog or standard structured logging

Do not adopt these merely because they are listed here; record architectural deviations and reasons.

## Package layout target

The final project name is unresolved; `research_platform` is a neutral placeholder.

```text
src/research_platform/
  domain/
  application/
  ports/
  adapters/
    discovery/
    acquisition/
    parsing/
    extraction/
    retrieval/
    reporting/
  infrastructure/
    postgres/
    artifacts/
  interfaces/
    cli/
    api/
    mcp/
```

Keep domain models separate from ORM models when doing so prevents persistence details from infecting core contracts.

## Configuration

Target precedence:

```text
defaults < config file < environment < CLI/runtime override
```

Use a clear prefix after final naming, e.g. `PROJECT_...` initially.

Secrets should be referenced through environment/secret providers, not stored in ordinary YAML.

## Error model

Use typed application/domain errors with stable error codes at interface boundaries.

Distinguish:

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

## Logging

Structured logs should include correlation identifiers:

- workspace ID
- job/run ID
- provider
- work/artifact ID
- stage
- duration
- outcome

Do not log full private source contents by default.

## Testing strategy

### Unit tests

- domain invariants
- identity normalization
- cache keys
- rights policy
- extraction contract validation

### Contract tests

Every plugin/adapter interface should have shared contract tests.

### Integration tests

- PostgreSQL repositories
- artifact store
- provider fixture normalization
- parser fixture integration

### End-to-end tests

Use small deterministic corpora and mocked/network-recorded provider fixtures.

Initial golden flow:

```text
local file
 -> hash/store artifact
 -> parse
 -> normalized document
 -> section/passage persistence
 -> manifest retrieval
```

## Reproducibility

Where practical, tests and research workflows should record versions/configuration. Avoid live-network dependencies in normal unit/CI test suites.

## Database migrations

Migrations are append-only historical artifacts after release. Avoid rewriting published migration history.

Migration design should preserve:

- referential integrity
- explicit uniqueness
- time/version metadata
- efficient common retrieval paths
- ability to store source-attributed conflicting observations

## Performance philosophy

Optimize after instrumenting, except for architectural choices that would make efficient operation impossible.

Measure:

- documents/minute
- parser latency
- extraction latency/cost
- database query latency
- vector search latency
- cache hit rate
- artifact deduplication rate
- agent context bytes/tokens per task

## Pull request expectations

Each nontrivial PR should state:

- problem
- design/approach
- affected contracts
- tests
- migration implications
- security/rights implications
- observability implications
- compatibility concerns

## Dependency policy

Prefer existing mature assets over custom implementations, but keep them behind ports/adapters when they are external architectural choices.

For large dependencies, document:

- why needed
- license
- alternatives
- transitive/security impact
- external network behavior
- replacement boundary

## Definition of done

A feature is not done because the happy path runs. It should include appropriate:

- input validation
- failure behavior
- tests
- logging/metrics hooks
- docs
- provenance/version metadata
- migration strategy
- token/context impact for agent-facing changes
