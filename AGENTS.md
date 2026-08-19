# AGENTS.md

## Purpose

This repository is a documentation-first foundation for a domain-agnostic research infrastructure platform. Coding agents must preserve the architectural contracts before optimizing for implementation speed.

## Read progressively

Do **not** load every document immediately.

Start with:

1. `README.md`
2. `docs/PROJECT_CHARTER.md`
3. the one architecture document relevant to the task

Load additional docs only when the task touches them:

| Task | Read |
|---|---|
| core/domain design | `docs/CANONICAL_DATA_MODEL.md` |
| service/module boundaries | `docs/ARCHITECTURE.md` |
| ingestion/workflows | `docs/RESEARCH_PIPELINE.md` |
| plugins/adapters | `docs/CONNECTOR_PLUGIN_SPEC.md` |
| MCP/agent APIs | `docs/AGENT_INTERFACE.md`, `docs/CONTEXT_EFFICIENCY.md` |
| auth/privacy/content rights | `docs/SECURITY_PRIVACY_LICENSING.md` |
| implementation sequencing | `docs/ROADMAP.md`, `docs/DEVELOPMENT.md` |
| naming/package namespace | `docs/NAMING.md` |
| external projects/dependencies | `docs/REFERENCE_PROJECTS.md` |

This is intentional progressive disclosure to conserve context.

## Core invariants

Do not violate these without an explicit architecture decision:

- Domain core is independent of specific research providers, parsers, LLM vendors, web frameworks, and databases.
- External systems are accessed through narrow adapters/ports.
- PostgreSQL is the reference metadata system of record; pgvector is the initial vector strategy.
- Raw artifacts are content-addressed and separate from normalized research records.
- Claims are distinct from evidence and citations.
- Important derived data preserves provenance.
- Rights/access/storage/redistribution/commercial-use concerns are modeled separately.
- Domain-specific semantics belong in domain packs or downstream integrations.
- Agent interfaces use progressive disclosure rather than returning full documents by default.
- CLI/API/MCP/SDK should share application services.
- Expensive pipeline stages should be resumable/idempotent where practical.

## Before creating code

1. Search the repository for an existing contract or concept.
2. Prefer extending existing assets over creating duplicate abstractions.
3. Identify the correct layer: domain, application, port, adapter, infrastructure, or interface.
4. Check whether the change affects provenance, rights, caching/versioning, or agent context cost.
5. Add or update tests with the implementation.

## Implementation style

- Prefer explicit, readable Python.
- Use type hints throughout public/internal contracts.
- Use composition and protocols/interfaces over inheritance-heavy frameworks.
- Validate external inputs at boundaries.
- Fail safely and return actionable typed errors.
- Use structured logging.
- Keep network calls out of domain logic.
- Avoid hidden global state.
- Make concurrency/rate limiting explicit at orchestration boundaries.
- Never log secrets or private full document contents by default.

## Dependency rule

Before adding a substantial dependency, determine:

- existing repository capability
- why the dependency is needed
- license compatibility
- replacement boundary
- network/data behavior
- test strategy

Do not recreate mature parsing/search/reporting systems merely to avoid integration work.

## Agent/token efficiency

For agent-facing features:

- manifest first
- summary second
- evidence on demand
- full content only when required
- return stable handles/IDs
- include pagination/cursors
- include estimated result size where useful
- prefer sequential capability/schema discovery

Read `docs/CONTEXT_EFFICIENCY.md` before changing MCP/tool contracts.

## Testing expectations

Use the smallest appropriate level:

- unit tests for domain logic
- shared contract tests for adapters
- integration tests for PostgreSQL/artifact storage
- deterministic end-to-end fixtures for pipeline slices

Do not depend on live external APIs in normal unit tests.

## Scope discipline

Avoid large speculative frameworks. Implement the current roadmap milestone and leave explicit extension points.

If documentation and code disagree, treat the conflict as a design issue: update the relevant architecture document in the same change or explain why it is intentionally superseded.

## Progress reporting

For substantial work, maintain a concise task record in the PR/issue or working notes containing:

- goal
- decisions
- files changed
- tests/validation
- unresolved questions

Do not create permanent project-management files for every temporary task unless the repository adopts such a convention.
