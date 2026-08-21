# AGENTS.md

## Purpose

Tarkka is a domain-agnostic research infrastructure platform with an implemented local ingestion kernel and scholarly-discovery layer. Coding agents must preserve the architectural contracts and evidence/provenance guarantees before optimizing for implementation speed.

This file is the shared repository instruction source for Codex, Claude, and other coding agents. Tool-specific instruction files should extend it only when they have genuinely tool-specific behavior; do not duplicate these rules into parallel files.

## Read progressively

Do **not** load every document immediately.

Start with:

1. `README.md`
2. `docs/PROJECT_CHARTER.md`
3. the one architecture document relevant to the task

Load additional docs only when the task touches them:

| Task | Read |
|---|---|
| current implementation sequence/status | `docs/ROADMAP.md`, latest `docs/MILESTONE_*.md` |
| core/domain design | `docs/CANONICAL_DATA_MODEL.md` |
| service/module boundaries | `docs/ARCHITECTURE.md` |
| source/document preservation, formats, crawling, citations | `docs/SOURCE_DOCUMENT_PRESERVATION.md` |
| ingestion/workflows | `docs/RESEARCH_PIPELINE.md` |
| plugins/adapters | `docs/CONNECTOR_PLUGIN_SPEC.md` |
| MCP/agent APIs | `docs/AGENT_INTERFACE.md`, `docs/CONTEXT_EFFICIENCY.md` |
| auth/privacy/content rights | `docs/SECURITY_PRIVACY_LICENSING.md` |
| implementation practices | `docs/DEVELOPMENT.md` |
| naming/package namespace | `docs/NAMING.md` |
| unresolved design choices | `docs/OPEN_QUESTIONS.md` |
| external projects/dependencies | `docs/REFERENCE_PROJECTS.md` |

This is intentional progressive disclosure to conserve context.

## Core invariants

Do not violate these without an explicit architecture decision:

- Domain core is independent of specific research providers, parsers, LLM vendors, web frameworks, and databases.
- External systems are accessed through narrow adapters/ports.
- **Preserve native structure first; normalize second; infer last.**
- Source-native facts, parser-reconstructed observations, and model/OCR/vision inferences are distinct layers and must not overwrite one another.
- Adapters must not silently discard provider-native information merely because Tarkka has not promoted it to a canonical typed field yet; preserve a bounded native observation or immutable artifact reference.
- Application orchestration should select replaceable adapters by capability/contract rather than provider-name branching when a capability contract exists.
- Crawlers discover/acquire resources and preserve resource relationships; they do not create canonical research identity or embed parser/research semantics directly.
- Citation mentions, bibliography entries, resolved citations, claims, and evidence are separate concepts.
- PostgreSQL is the reference metadata system of record; pgvector is the initial vector strategy when vector retrieval is implemented.
- Raw artifacts are content-addressed and separate from normalized research records.
- Acquisition/source provenance is separate from artifact content identity.
- Claims are distinct from evidence and citations.
- Important derived data preserves provenance and version information.
- Rights/access/storage/redistribution/commercial-use concerns are modeled separately.
- Domain-specific semantics belong in domain packs or downstream integrations.
- Agent interfaces use progressive disclosure rather than returning full documents by default.
- Provider selection, cross-provider identity, and enrichment are separate application concerns; provider adapters do not call one another.
- Ambiguous/fuzzy identity must not silently collapse records.
- CLI/API/MCP/SDK should share application services.
- Expensive pipeline stages should be resumable/idempotent where practical.
- Core operation must not require an LLM.

## Before creating code

1. Search the repository for an existing contract or concept.
2. Prefer extending existing assets over creating duplicate abstractions.
3. Identify the correct layer: domain, application, port, infrastructure/adapter, or interface.
4. Check the current roadmap/milestone rather than starting speculative future layers.
5. Check whether the change affects provenance, rights, identity, caching/versioning, pagination, or agent context cost.
6. For provider/parser/crawler changes, inventory what the external source exposes before choosing normalized mappings; explicitly consider identifiers, references/citations, alternate/full-text/supplement links, versions/corrections/retractions, rights, and native structure.
7. Add or update tests with the implementation.
8. Update architecture/milestone docs when behavior or contracts materially change.

## Implementation style

- Prefer explicit, readable Python.
- Use lowercase `tarkka` for machine-facing package/CLI/schema identifiers unless an external system requires otherwise.
- Use type hints throughout public/internal contracts.
- Use composition and protocols/interfaces over inheritance-heavy frameworks.
- Validate external inputs at boundaries.
- Fail safely and return actionable typed/interface errors.
- Preserve useful exception context for infrastructure/provider failures.
- Use structured logging as observability is introduced.
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

Do not recreate mature parsing/search/reporting systems merely to avoid integration work, but do not make a vendor library the architecture either.

## Agent/token efficiency

For agent-facing features:

- capability metadata first
- manifest first
- summary/structured finding second
- evidence on demand
- full content only when required
- return stable handles/IDs
- include pagination/cursors
- include estimated result size/token cost where useful
- prefer sequential capability/schema discovery

Read `docs/CONTEXT_EFFICIENCY.md` before changing MCP/tool contracts.

## Testing expectations

Use the smallest appropriate level:

- unit tests for domain/application logic
- shared contract tests for replaceable adapters
- integration tests for PostgreSQL/artifact/parser boundaries
- deterministic end-to-end fixtures for pipeline slices

Do not depend on live external APIs in normal unit/CI tests. External provider responses are untrusted fixture boundaries and should include malformed/edge cases where relevant.

For source/document adapters, tests should assert **preservation**, not merely successful parsing. Representative fixtures should catch silent loss of identifiers, bibliography, citation anchors, figures, tables, equations, supplements/resource links, and provider-specific observations as those capabilities are implemented.

## Scope discipline

Avoid large speculative frameworks. Implement the current roadmap milestone and leave explicit extension points.

If documentation and code disagree, treat the conflict as a design issue: update the relevant architecture/status document in the same change or explain why it is intentionally superseded.

Do not reopen decisions listed as resolved merely because an older planning document or automated review comment suggests a different direction. Verify against the current code, current docs, and current upstream documentation.

## Progress reporting

For substantial work, maintain a concise task record in the PR/issue containing:

- goal
- decisions
- files/contracts changed
- tests/validation
- unresolved questions

Do not create permanent project-management files for every temporary task unless the repository adopts such a convention.
