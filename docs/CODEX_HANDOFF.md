# Codex Handoff — Tarkka

**Handoff date:** 2026-08-24  
**Repository:** `cbwinslow/Tarkka`  
**Default branch:** `main`  
**Baseline at handoff:** PR #131 merged as `15ea46cbc2b43e41329824f1dd3cebd1b28db215`  
**Primary next engineering issue:** #132 — Wire configurable `WorkRepository` backend into CLI runtime

> This document is a current execution snapshot for Codex. It does **not** replace `AGENTS.md`.
> Read and obey `AGENTS.md` first. When this handoff, older planning text, automated review comments,
> or stale issues disagree with the current repository, verify against current code, `AGENTS.md`,
> `docs/ROADMAP.md`, and the relevant architecture document before acting.

---

## 1. Mission

Tarkka is a free/open-source, domain-agnostic research infrastructure platform for turning
heterogeneous research sources into structured, evidence-linked, reproducible, agent-friendly
knowledge.

The system is intended to connect the full research lifecycle without coupling the architecture to
one research domain, LLM provider, parser, discovery provider, database implementation, or retrieval
strategy.

A successful end state lets a user:

1. define a research workspace/question,
2. discover research from multiple providers,
3. acquire and ingest local/remote artifacts,
4. preserve source-native structure and provenance,
5. resolve canonical Works and identifiers,
6. extract typed research objects,
7. verify claims against exact evidence,
8. search/retrieve progressively and efficiently,
9. serve research to agents through compact stable interfaces,
10. export reproducible evidence-linked reports and datasets,
11. extend the generic core through domain packs rather than domain forks.

Reference validation domains are MLB/baseball research and finance/economics, but **domain-specific
semantics must not leak into the generic core**.

---

## 2. Required reading order

Do not load the entire repository documentation into context at once. Follow the progressive-reading
contract in `AGENTS.md`.

Start with:

1. `AGENTS.md`
2. `README.md`
3. `docs/PROJECT_CHARTER.md`
4. `docs/ROADMAP.md`
5. the architecture document relevant to the current task

For #132 specifically also read:

- `src/tarkka/interfaces/cli.py`
- `src/tarkka/ports/works.py`
- `src/tarkka/infrastructure/storage/json_work_repository.py`
- `src/tarkka/infrastructure/postgres/work_repository.py`
- `src/tarkka/infrastructure/postgres/connection.py`
- `tests/contracts/work_repository.py`
- `tests/test_json_work_repository_contract.py`
- `tests/test_postgres_work_repository_contract.py`
- `tests/test_postgres_work_repository_unit.py`
- `.github/workflows/postgres-work-repository.yml`
- `docs/MILESTONE_3.md`

Do not infer repository behavior from this handoff alone. Inspect the current implementation before
editing.

---

## 3. Operating contract

### Evidence and provenance come before convenience

The most important architectural rule is:

> **Preserve native structure first; normalize second; infer last.**

Generated synthesis is secondary to verifiable evidence. Every important derived object should make
it cheap to answer: **where did this come from, what transformed it, and can we reconstruct the
relationship?**

Keep these layers separate:

- source-native observations,
- parser-reconstructed observations,
- model/OCR/vision inference,
- canonical normalized records,
- claims/research objects,
- evidence,
- citation/bibliography relationships,
- human review decisions.

Never overwrite one layer with another simply because the newer layer looks more convenient.

### Stable core, replaceable adapters

The domain/application core must remain independent of:

- OpenAlex, Crossref, Semantic Scholar, arXiv, or future research providers,
- Docling/JATS/EPUB/HTML or future parsers,
- OpenAI/OpenRouter/other model vendors,
- PostgreSQL/JSON implementation details,
- web frameworks,
- crawlers,
- vector databases.

Use narrow ports/protocols and capability contracts. Prefer extending an existing contract over
creating a parallel abstraction.

### Canonical identity belongs to Tarkka

Provider identifiers and observations are evidence about a Work; they are not the canonical Work
identity themselves.

- Strong identifiers such as normalized DOI/arXiv IDs may establish identity through explicit rules.
- Fuzzy identity is review-only unless an explicit reconciliation workflow is implemented.
- Never silently collapse ambiguous Works.
- Provider adapters must not call one another to resolve identity.

### Raw artifacts and metadata are distinct

- Raw bytes are immutable/content-addressed artifacts.
- Acquisition/source provenance is separate from artifact content identity.
- Canonical metadata is not a substitute for retaining source observations.
- Unknown provider-native fields should remain recoverable through bounded native metadata or an
  immutable artifact reference.

### Core operation must not require an LLM

LLM/model-assisted extraction is optional. Deterministic ingestion, identity, persistence, and core
research workflows must continue to work without model credentials.

### Progressive disclosure for agents

Agent interfaces should generally return:

1. capabilities/manifest,
2. compact metadata or structured findings,
3. evidence handles,
4. exact evidence on request,
5. full source content only when actually required.

Stable IDs, cursors/pagination, and bounded outputs are preferred over dumping corpora into context.

---

## 4. Development contract

### Package/environment tooling

Use `uv`. Do not introduce a parallel Poetry/pip/requirements development workflow.

Canonical setup:

```bash
uv sync --group dev
```

Canonical local validation for normal Python/SQL changes:

```bash
uv run ruff check .
uv run mypy
uv run sqlfluff lint migrations
uv run pytest -m "not external"
```

Do not hand-edit `uv.lock`. If dependencies change, use `uv`, inspect the lock diff, and commit it in
the same PR.

### Implementation style

- explicit readable Python,
- comprehensive typing at contracts/boundaries,
- protocols/composition over inheritance-heavy frameworks,
- validate external inputs at boundaries,
- fail closed on ambiguous/invalid configuration,
- keep network calls out of domain logic,
- avoid hidden global state,
- make concurrency/rate limits explicit,
- parameterize SQL,
- preserve exception context without leaking secrets/private document contents,
- reuse existing assets instead of adding speculative frameworks.

### Scope discipline

Before creating a new type/module/service:

1. search for an existing concept,
2. identify the proper layer,
3. inspect the current roadmap/status,
4. check provenance/identity/rights/versioning implications,
5. add tests with the implementation,
6. update status/architecture docs when behavior materially changes.

Avoid “future-proof” abstractions that have no current caller. Extension points are good; duplicate
frameworks are not.

---

## 5. Testing contract

Use the smallest test level that proves the behavior:

- unit tests for domain/application behavior,
- shared contract tests for replaceable adapters,
- integration tests for PostgreSQL/artifact/parser boundaries,
- deterministic end-to-end fixtures for pipeline slices,
- property-based tests for broad invariants/boundary classes,
- external/live provider tests only in isolated opt-in jobs.

Normal CI must remain network-free and credential-free.

Every meaningful correctness bug should gain a regression test. If a bug exposes a broader backend or
contract invariant, encode it in the shared contract rather than only in one adapter-specific test.

For parsers/providers, test **preservation**, not just “parsing succeeded.” Silent loss of identifiers,
bibliography, citation anchors, figures, tables, equations, supplements, links, or native observations
is a correctness failure.

---

## 6. GitHub / CI operating contract

Deterministic CI is authoritative. AI reviewers are advisory.

Current important automation includes:

- `ci.yml`
  - `uv lock --check`
  - frozen development sync
  - Ruff
  - strict MyPy
  - SQLFluff for migrations
  - zizmor GitHub Actions security audit
  - pytest on Python 3.11 / 3.12 / 3.13
  - Python 3.13 branch coverage
  - 80% changed-line coverage enforcement on PRs
  - retained JUnit/coverage artifacts
- `package.yml`
  - build wheel and sdist
  - validate both in independent clean environments
  - import + `tarkka --help` smoke tests
- `dependency-review.yml`
  - dependency submission + vulnerability review using least privilege
- `security-regression.yml`
  - scheduled security/property regressions
- `docling.yml`
  - isolated real Docling integration
- `postgres-work-repository.yml`
  - real PostgreSQL service contract for Work persistence
- `labeler.yml`
  - path-based PR labels
- `pr-agent.yml`
  - OpenRouter PR-Agent review
- `opencode-review.yml`
  - independent advisory OpenCode Zen review when configured

Action versions should remain immutably SHA-pinned. Do not replace these with floating tags.

### Reviewer policy

Primary PR-Agent model is intentionally:

```text
openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
```

Keep paid fallbacks disabled unless the owner explicitly changes that policy.

The OpenCode Zen reviewer is separate/advisory. Its model is configurable through the repository
variable `OPENCODE_REVIEW_MODEL`; current code has a free default. Model catalogs change, so verify
current OpenCode documentation before changing model IDs.

Never make external AI-provider availability a required deterministic merge gate.

### Merge discipline

Before merging a code PR:

1. inspect the exact current head,
2. read all unresolved review threads,
3. validate reviewer findings instead of applying them mechanically,
4. fix material correctness/security/provenance issues,
5. add regression/contract tests for material fixes,
6. ensure required deterministic checks are green on the **final head**,
7. inspect external statuses for additional material findings,
8. resolve review threads with a fix or a technical rationale,
9. merge only the reviewed/validated head.

Do not treat “CI green” as equivalent to “correct.” PR #131 is a concrete example: CI was green before
reviewers found real transaction-isolation and timestamp-semantics bugs.

---

## 7. Repository protection / workflow expectations

The checked-in main ruleset reference is under `.github/rulesets/` and requires the deterministic core
checks while keeping path-filtered integrations and AI reviewers advisory.

Do not add duplicate generic branch-protection workflows simply to have more Actions.

Repository-level settings that may still require manual GitHub UI verification include:

- CodeQL default setup,
- secret scanning,
- push protection,
- automatic deletion of merged head branches,
- optional repository-wide auto-merge/update-branch settings.

Do not claim these account-level/repository-level controls are enabled unless verified through GitHub.

---

## 8. Completed project state

### Phase 0 — Foundation

Complete. Core project/architecture/development/agent documents and naming foundations exist.

### Phase 1 — Local vertical slice

Substantially complete. Existing capabilities include:

- typed Python package/domain core,
- local SHA-256 content-addressed artifact storage,
- separate acquisition provenance,
- local metadata storage,
- PostgreSQL reference schema/migrations,
- PostgreSQL Work persistence adapter,
- text/Markdown parsing,
- optional Docling,
- JATS, EPUB, and semantic HTML paths,
- canonical `Artifact -> Document -> Section -> Passage` normalization,
- Figure/Table/Equation source artifacts,
- resource manifests,
- CLI ingest/inspect/read,
- parser contracts/integration tests.

Phase 1 items remain intentionally demand-driven: broader PostgreSQL repositories, observability,
PostgreSQL FTS/pgvector retrieval, and later chunk/index work.

### Phase 2 — Scholarly discovery and identity

Complete for the local/offline workflow.

Delivered:

- provider-neutral discovery contracts,
- capability-aware provider selection,
- `auto`, explicit, and `all` modes,
- broad/preprint/citations/bibliographic intents,
- OpenAlex, Crossref, Semantic Scholar, arXiv adapters,
- bounded concurrent fan-out and continuation cursors,
- retry/rate-limit behavior,
- reproducible SearchSnapshots,
- DOI/arXiv strong identity normalization,
- Tarkka-owned canonical Work identity,
- identifier aliases and source/provider observations,
- Crossref DOI enrichment,
- full-text acquisition,
- review-only fuzzy identity candidates and decisions,
- Work CLI flows,
- JSON and PostgreSQL Work repositories sharing a behavioral contract.

### Phase 3 — Structured research extraction/source intelligence

In progress but already substantial.

Delivered foundation includes:

- generalized Evidence with passage/Figure/Table/Equation locators,
- extraction-run provenance,
- review state and stated-vs-inferred attribution,
- Claim, Hypothesis, Method, Dataset, Variable, Model, Metric, Result, Limitation,
- structured extraction ports/postconditions,
- extraction repository contract,
- PostgreSQL extraction reference schema,
- deterministic claim extraction,
- JSON extraction persistence,
- claim/evidence CLI inspection,
- OpenAI-compatible extraction boundary,
- extraction evaluation fixtures/metrics,
- bounded model requests,
- request-local evidence validation,
- semantic-overlap deduplication,
- property-based batching tests.

The source/document intelligence sequence #25–#28 has also already been completed:

- #25 source-observation/capability contracts,
- #26 bibliography/citation/Work-relation model,
- #27 native-structure adapters/preservation fixtures,
- #28 bounded web/resource discovery/acquisition architecture.

Do not reopen or duplicate these merely because `docs/ROADMAP.md` still labels them as a “current
sequence.” Verify what is actually missing.

Existing source-intelligence primitives include:

- `SourceObservation`,
- `ObservationBasis` (`native`, `reconstructed`, `inferred`),
- `CapabilityManifest`,
- `ResourceLinkObservation`,
- resource relations including full text, supplement, dataset, software, citation, version,
  correction, retraction,
- bibliography/citation context types,
- `WorkRelation` with provenance,
- bounded resource acquisition policies,
- source-observation persistence.

---

## 9. Work just completed before this handoff

PR #131 — **Implement PostgreSQL WorkRepository adapter** — is merged.

Merge commit:

```text
15ea46cbc2b43e41329824f1dd3cebd1b28db215
```

Issue #130 closed automatically with the merge.

The final implementation was deliberately strengthened during review.

### Important final semantics

- PostgreSQL Work persistence is validated against the same reusable contract as JSON persistence.
- Transaction connection state is stored in a per-repository `ContextVar`, preventing unrelated
  execution contexts from accidentally sharing one active transaction connection.
- Nested repository transactions remain rejected.
- Standalone operations commit.
- Failed explicit transactions roll back atomic Work/identifier/source-record changes.
- Expected identifier/source-record ownership conflicts are translated to backend-neutral
  `ValueError` behavior instead of leaking database-specific expected-conflict exceptions.
- SQL is parameterized and schema-qualified.
- JSONB Work/source-record content round-trips through the domain model.
- Work `created_at` is immutable during metadata evolution in both JSON and PostgreSQL backends.
- Identifier binding `created_at` is also immutable/idempotent in both backends.
- Provider source-record `observed_at` remains refreshable because it represents a later observation
  of the provider record under the current unique-key model.
- `updated_at` currently remains a PostgreSQL storage concern and is not promoted into the generic
  `Work` domain type merely because the column exists.
- Ordering provider/source columns do not need to be projected just to satisfy PostgreSQL `ORDER BY`;
  do not inflate return shapes for a non-problem.

### CI/security changes included in #131

The PostgreSQL integration workflow:

- uses PostgreSQL 17 Alpine,
- runs with an ephemeral Actions-only database,
- uses trust auth inside that isolated runner rather than committing a fake static password,
- uses `uv`, frozen lock state, and the optional `postgres` extra,
- applies required migrations,
- runs the real PostgreSQL Work repository contract,
- retains JUnit output,
- is path-filtered so unrelated PRs do not pay for a database service.

The final #131 head passed:

- Ruff,
- strict MyPy,
- SQLFluff,
- zizmor,
- Python 3.11 / 3.12 / 3.13 tests,
- branch coverage,
- changed-line coverage,
- package build/install validation,
- dependency review,
- real PostgreSQL contract tests,
- PR-Agent/Nemotron review,
- external statuses including CommitCheck, CodeRabbit, pre-commit.ci, and Qlty.

All material review threads were resolved before merge.

---

## 10. Current repository queue

At handoff there are **zero open pull requests**.

Important open issues:

### #132 — Wire configurable WorkRepository backend into CLI runtime

This is the immediate next engineering task.

Why it matters: `PostgresWorkRepository` is implemented and tested, but normal Work CLI flows still
hardcode `JsonWorkRepository`. The PostgreSQL adapter therefore exists without a normal runtime
composition path.

Required behavior:

- add explicit `TARKKA_WORK_BACKEND` configuration,
- supported values: `json`, `postgres`,
- default remains `json`,
- do **not** auto-switch to PostgreSQL just because `TARKKA_DATABASE_URL` exists,
- `TARKKA_WORK_BACKEND=postgres` constructs `PostgresWorkRepository` from
  `PostgresSettings.from_environment()`,
- invalid backend names fail closed with a clear error,
- PostgreSQL selection without a valid database URL fails clearly before useful Work operations,
- type interface helpers against `WorkRepository`, not `JsonWorkRepository`,
- do not make `psycopg` a required core dependency,
- add unit tests for backend selection/configuration failure paths,
- extend real PostgreSQL integration coverage to prove the configured runtime/CLI path can persist and
  read a Work,
- update roadmap/runtime docs so PostgreSQL Work persistence is no longer described as unwired.

Acceptance criteria are already written in GitHub issue #132. Read the live issue before implementing.

### #72 — Choose project license and release policy

This is intentionally an **owner/policy decision**, not an autonomous coding decision.

Do not choose a project license, enable public PyPI publishing, or establish commercial/release terms
without explicit owner direction.

Release automation remains deliberately deferred until the license/distribution policy is settled.

### #133

This was an accidental placeholder created while probing the GitHub action surface. It is closed
`not_planned` and tracks no project work. Ignore it.

---

## 11. Recommended execution for #132

Work in a focused branch/PR. Keep the patch small.

### Step 1 — inspect current contracts

Read the files listed in Section 2. Confirm the live code has not changed since this handoff.

### Step 2 — design the runtime selector at the interface/composition boundary

Do **not** push environment parsing into the domain model.

A reasonable small shape is an interface-level factory/helper that returns `WorkRepository` based on
an explicit normalized environment value.

Desired policy:

```text
TARKKA_WORK_BACKEND unset/empty -> json
TARKKA_WORK_BACKEND=json        -> JsonWorkRepository
TARKKA_WORK_BACKEND=postgres    -> PostgresWorkRepository(PostgresSettings.from_environment())
anything else                   -> fail closed
```

Keep the local default backward compatible.

### Step 3 — type against the port

Any helper such as `_work_repository()` and payload/service helper that only requires the
`WorkRepository` contract should be annotated with `WorkRepository`, not the concrete JSON class.

Do not widen abstractions unrelated to this task.

### Step 4 — test configuration behavior

Add focused tests that prove:

- default -> JSON,
- explicit JSON -> JSON,
- explicit PostgreSQL -> PostgreSQL,
- invalid backend -> clear failure,
- explicit PostgreSQL without required DB configuration -> clear failure,
- presence of `TARKKA_DATABASE_URL` alone does **not** switch the backend.

Avoid requiring a real DB for pure selection tests. Dependency injection/patching at the composition
boundary is appropriate.

### Step 5 — prove the real configured PostgreSQL path

Extend the existing PostgreSQL integration workflow/test so it goes through the same runtime selector
used by the CLI, then performs at least one real persist/read path.

Do not create a second PostgreSQL workflow if the existing path-filtered workflow can own the test.

### Step 6 — documentation

Update at least the relevant runtime/development/roadmap text to document:

```bash
TARKKA_WORK_BACKEND=postgres
TARKKA_DATABASE_URL=postgresql://...
```

Be explicit that JSON remains the default and PostgreSQL currently applies to Work persistence only,
not every repository in Tarkka.

### Step 7 — validate and review

Run local checks, open the PR, then treat all reviewer comments as hypotheses to validate.

Do not merge until the final head has green deterministic CI and the real PostgreSQL path is green.

---

## 12. What should follow #132

After production Work wiring is real, return to the Phase 3 roadmap rather than adding infrastructure
for its own sake.

### Likely next Phase 3 slice: research packages / supplements

The primitives already exist. Do **not** create a second relation framework.

Current domain already has:

- `ResourceLinkObservation`,
- `ResourceRelation.SUPPLEMENT`,
- `ResourceRelation.DATASET`,
- `ResourceRelation.SOFTWARE`,
- `WorkRelationKind.USES_DATASET`,
- `WorkRelationKind.USES_SOFTWARE`,
- `WorkRelationKind.SUPPLEMENTS`,
- source observation provenance,
- artifact acquisition/ingestion infrastructure.

The missing piece should be framed as application orchestration that can group/resolve
source-observed article representations, supplements, datasets, and code into a coherent research
package while preserving provenance and ambiguity.

Important constraints:

- not every linked resource is automatically a canonical Work,
- preserve the source-observed link before resolving it,
- prefer linked raw/supplementary data over reconstructing values from chart pixels when available,
- avoid creating duplicate relationship types,
- keep identity resolution separate from crawling/parsing,
- retain rights/access information as distinct concerns.

### Then Phase 4 — evidence verification

The next major product capability after structured extraction/source intelligence is to distinguish
**citation** from **actual evidentiary support**.

Expected direction:

- claim/evidence relationships,
- citation-context-aware verification,
- support / contradiction / qualification labels,
- confidence/review state,
- exact passage/Figure/Table expansion,
- bounded cited-source traversal,
- deterministic evaluation fixtures.

Do not jump straight to MCP/agent serving before the evidence-verification contract is useful enough
to serve.

---

## 13. Security and data handling

- Never commit credentials, API keys, private URLs, or user document contents.
- Do not log model/provider tokens.
- Keep normal CI credential-free.
- Treat all provider/parser/model output as untrusted input.
- Resource acquisition must remain fail-closed and bounded.
- Existing acquisition policy rejects unsafe network targets unless explicitly allowed; do not weaken
  SSRF/private-address protections casually.
- Rights/access/storage/redistribution/commercial-use are separate policy dimensions.
- Do not advertise institutional/multi-tenant readiness before those controls actually exist.

For GitHub workflows carrying secrets, never execute untrusted PR-head code through a secret-bearing
`pull_request_target` path. The OpenCode reviewer is intentionally designed around trusted-base
execution for this reason.

---

## 14. External integrations / freshness rules

Research providers, GitHub Actions, model IDs, APIs, and package behavior change over time.

Before changing integration-specific behavior:

1. inspect current upstream documentation,
2. preserve current project contracts unless upstream behavior requires a deliberate change,
3. isolate vendor-specific details inside adapters,
4. add deterministic fixtures/contract tests for the behavior we depend on.

Do not rely on an old automated review comment as current upstream documentation.

---

## 15. Progress reporting expectations for Codex

For substantial work, keep the GitHub issue/PR description current with:

- goal,
- architectural decisions,
- important files/contracts changed,
- tests run,
- review findings fixed/rejected with rationale,
- unresolved questions,
- next step.

Do not create a new permanent status Markdown file for every task. This handoff is a deliberate
cross-agent transition artifact; normal task progress belongs in the issue/PR.

When handing work back to the owner, provide a concise status such as:

```text
PR #___ is ready/not ready.
Implemented: ...
Validated: ...
Material review findings: ...
Remaining blocker/manual action: ...
Next recommended issue: ...
```

Do not hide known failing tests, skipped required integrations, or unresolved material reviewer
findings.

---

## 16. Definition of “done” for the immediate handoff

Codex should consider this handoff successfully consumed when it has:

1. read `AGENTS.md` and the current roadmap,
2. inspected issue #132 and the current Work persistence implementations,
3. implemented explicit Work backend runtime selection without changing the JSON default,
4. added focused configuration/unit tests,
5. extended real PostgreSQL integration coverage through the runtime selection path,
6. updated runtime/roadmap documentation,
7. opened a focused PR,
8. reviewed/fixed material comments,
9. obtained green final-head deterministic CI and real PostgreSQL integration,
10. merged the PR if repository rules permit and the reviewed head is clean,
11. confirmed #132 closes,
12. re-audited open PRs/issues and then scoped the next Phase 3 research-package/supplement slice.

If #132 is already completed when Codex starts, do not recreate it. Verify the merged behavior and move
to the next genuine roadmap gap.

---

## 17. Final reminder

Tarkka is not intended to become a collection of disconnected scripts or AI-generated abstractions.
The project is a **research evidence system** whose value comes from stable identities, preserved
source observations, exact evidence relationships, reproducible transformations, replaceable
adapters, and compact agent-facing access.

Optimize for those properties first. Optimize for implementation speed second.
