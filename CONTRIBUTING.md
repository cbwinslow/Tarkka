# Contributing

Thanks for helping build the research platform.

## Current project stage

The repository is in an architecture-first bootstrap phase. Small, well-bounded changes that strengthen contracts, tests, adapters, or documentation are preferred over large speculative frameworks.

## Before starting

Read:

1. `README.md`
2. `AGENTS.md`
3. `docs/PROJECT_CHARTER.md`
4. the task-relevant design document

Search existing issues/code before creating a new abstraction.

## Development setup

Tarkka uses `uv` as the canonical Python project and development environment manager. The package metadata remains standards-based in `pyproject.toml`, and Hatchling is the build backend.

Install a compatible `uv` release, then create/synchronize the development environment from the project root:

```bash
uv sync --group dev
```

Run project tooling through `uv run` rather than relying on globally installed Python tools:

```bash
uv run ruff check .
uv run mypy
uv run sqlfluff lint migrations
uv run pytest -m "not external"
```

When the lockfile changes intentionally, review the dependency diff before committing it. Do not hand-edit `uv.lock`.

Development-only tooling belongs in the `dev` dependency group. Runtime dependencies belong in `[project.dependencies]` or a narrowly scoped optional extra such as `postgres` or `docling`.

## Good early contributions

- architecture review and concrete corrections
- typed domain model prototypes
- provider/parser adapter prototypes behind documented contracts
- fixtures and benchmark corpora that are legally redistributable
- contract tests
- retrieval/context-efficiency benchmarks
- documentation improvements
- source-rights metadata design
- domain-pack examples

## Pull request expectations

A nontrivial PR should explain:

- problem and user value
- approach
- contracts affected
- tests/validation
- migration/storage impact
- security/privacy/rights impact
- agent context/token impact when relevant
- known limitations

Keep unrelated refactors out of the same PR.

## Architecture changes

If a change intentionally contradicts a documented invariant, update the architecture document or add a decision record explaining why.

## Tests

Prefer deterministic tests and recorded/static fixtures over live external API dependencies.

External provider adapters should have shared contract tests for pagination, normalization, rate-limit behavior, provenance, and error handling.

See `docs/TESTING.md` for the marker taxonomy, CI contract, and canonical validation commands.

## Research/source contributions

Do not commit copyrighted or restricted full-text research merely because it is useful for testing.

Use:

- public-domain/openly licensed fixtures
- synthetic documents
- minimal excerpts only when legally appropriate
- scripts that let users obtain their own permitted sources

Document fixture provenance and license.

## Security

Do not include credentials, private research content, or user data in issues, fixtures, logs, or PRs.

Report security-sensitive issues privately once a security policy/contact is established; until then, avoid publishing exploitable details in public issues and contact the repository owner directly.

## Style and quality gates

Python contributions should be explicit, typed, and organized around focused modules and replaceable contracts. CI enforces:

- Ruff for Python linting/import hygiene
- strict mypy for static typing
- SQLFluff with the PostgreSQL dialect for migration SQL
- pytest across supported Python versions
- branch-coverage reporting on the primary CI interpreter

Prefer composition/protocols over inheritance-heavy frameworks, validate external inputs at boundaries, and avoid unnecessary framework coupling.

## Package-development rules

Keep the published package installable independently of development tooling:

- do not place linters, test frameworks, or documentation tooling in runtime dependencies;
- keep the `src/tarkka` layout and public CLI entry point standards-compliant;
- avoid importing optional integrations at package import time when their extras are not installed;
- add dependencies only when they materially improve the implementation and have a clear replacement boundary;
- preserve the supported `requires-python` contract or update CI and documentation with any deliberate compatibility change.

## License note

Tarkka is licensed under Apache-2.0. By submitting a contribution, you agree that it is
licensed under the repository's Apache-2.0 license and that you have the right to submit it.
Do not submit third-party code, fixtures, or research content unless its redistribution terms
permit doing so. The software license does not grant rights to imported research content.
