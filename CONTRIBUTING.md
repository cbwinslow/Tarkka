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

## Style

Implementation conventions will be finalized with the first code milestone. Until then:

- readable explicit Python
- type hints
- focused modules
- composition/protocols
- structured errors/logging
- no unnecessary framework coupling

## License note

The software license has not yet been selected. External contributions should remain minimal until the repository adopts an explicit license and contributor policy.
