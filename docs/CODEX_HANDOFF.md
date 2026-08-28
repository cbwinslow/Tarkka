# AI Handoff — Tarkka

**Handoff timestamp:** 2026-08-28 UTC  
**Repository:** `cbwinslow/Tarkka`  
**Default branch:** `main`  
**Active branch:** `test/phase5-coverage-hardening`  
**Active PR:** #184 — `test: harden Phase 5 coverage and scheduled security CI`  
**Canonical follow-up:** #185 — `test: ratchet historical branch coverage from 86% to 100%`  
**Current handoff head:** `61c67b491e8321098a933765a7faa93b5e9c45b7`

> This is the current execution snapshot for any coding agent, despite the historical filename.
> `AGENTS.md` remains authoritative. Read it first, then this handoff, then the canonical issue/PR.
> Verify all status claims against the current GitHub head before changing code.

---

## 1. Current objective

Finish PR #184 to a fully reviewed, fully green final head, then continue issue #185 by raising
historical branch coverage to 100% one coherent subsystem at a time.

The immediate engineering principles are:

- preserve Tarkka's existing architecture and provenance contracts;
- require 100% coverage for new/modified executable source lines;
- permanently ratchet completed subsystems to 100% branch coverage;
- review every automated-review finding rather than applying or dismissing it mechanically;
- leave an explicit GitHub/hand-off trail another agent can resume without reconstructing the session.

---

## 2. What PR #184 now contains

The PR took over the Codex Phase 5 work from PRs #176–#183 and hardened it rather than adding a new
feature layer.

Implemented/fixed:

- repaired the scheduled Security Regression workflow so the optional MCP dependency is installed in
  the CI profile that collects MCP tests;
- kept MCP tests safely optional in environments that do not install the `mcp` extra;
- raised changed-line coverage enforcement from 80% to 100%;
- changed the diff-coverage checker default to 100%;
- made diff-coverage failures print exact uncovered source lines;
- added a permanent 100% branch-coverage gate for the Phase 5 agent-serving/context-package/telemetry
  subsystem;
- added a cumulative 100% changed-line gate from the immutable pre-Phase-5 commit anchor;
- covered the complete recent Codex Phase 5 source diff from pre-PR #176;
- hardened MCP error/validation/backend-unavailable behavior;
- made optional MCP telemetry recorder failures non-fatal to research operations;
- added DEBUG diagnostic logging for telemetry recorder failures;
- expanded JSON and PostgreSQL context-package persistence failure-path tests;
- expanded research-capability schema/registration validation tests;
- expanded Phase 5 CLI failure/handle tests;
- documented the 100% coverage ratchet in `docs/TESTING.md`;
- added explicit PR-review and AI-handoff contracts to `AGENTS.md`.

Reviewer-driven improvements added after the first green head:

- PostgreSQL acquired connections are now explicitly tested for cleanup when a query fails after
  connection acquisition;
- transient PostgreSQL adapter tests no longer depend on uncontracted English wording;
- capability registration now tests both missing and existing-but-non-callable service attributes;
- telemetry validation overrides use a `TypedDict` instead of suppressing type errors;
- the non-POSIX fsync no-op has an explicit assertion;
- the MCP test helper is named/documented around structured-content semantics;
- the Phase 5 coverage include list is a maintainable shell array;
- the cumulative coverage anchor is centralized as `PHASE5_COVERAGE_BASE` and documented as an
  intentionally immutable commit SHA;
- the workflow explicitly documents that the cumulative coverage gate runs on PRs and pushes to
  `main` by design.

---

## 3. Coverage state

At the last fully green validated head before the final reviewer-driven cleanup:

- deterministic Python 3.13 suite: **1,019 passed, 36 deselected**;
- repository-wide historical branch coverage: approximately **86%**;
- Phase 5 agent-serving subsystem: **547 statements, 0 misses, 122 branches, 0 partial branches =
  100% branch coverage**;
- recent Codex Phase 5 source diff from pre-PR #176: **581/581 executable changed lines = 100%**;
- PR changed executable lines: **100%**.

Do not assume those exact test counts remain identical after later test additions. The invariant is the
coverage gate, not the count. Re-read the latest Python 3.13 CI job before updating PR #184's final
validation section.

Historical repository-wide 100% branch coverage is **not complete**. That debt is tracked in issue
#185. Do not mask it with exclusions or weak assertions.

---

## 4. Review-bot status and decisions

All inline threads that existed at this handoff were individually reviewed, replied to, and resolved.
The agent must still re-check after every new push because reviewers can post asynchronously.

Important dispositions already made:

### Applied

- log telemetry-recorder failures at DEBUG with exception context;
- make coverage include configuration maintainable;
- test PostgreSQL connection cleanup after post-acquisition failure;
- remove brittle retry-message matching from the repository adapter test;
- test existing non-callable capability service attributes;
- type telemetry test overrides rather than using `type: ignore`;
- make fsync no-op assertion explicit;
- clarify structured MCP test helper semantics.

### Intentionally retained

- `except Exception` around **only** `telemetry.record(event)`: optional observability must never alter
  the research operation result. Event construction/measurement logic remains outside that boundary,
  and recorder failures are now logged and tested.
- immutable pre-Phase-5 commit SHA: a movable tag/ref could silently weaken the historical coverage
  range. Advancing the anchor is an explicit coverage-policy change.
- cumulative Phase 5 coverage gate on pushes to `main`: this is a permanent post-merge ratchet, not a
  PR-only diagnostic.
- dated 86% coverage baseline in `docs/TESTING.md`: it is an auditable historical measurement, not a
  dynamically current claim.
- CLI `capsys.readouterr()` loop: reviewer claimed the second iteration would see an empty buffer, but
  each iteration invokes `main(command)` before reading/clearing capture, so fresh stderr exists each
  time; the supported Python matrix already exercises the test.
- no duplicate invalid-section-ID test in the focused MCP short-circuit file because the main MCP test
  suite already covers invalid string and non-string section IDs and the module is branch-covered.

A later Kilo comment requested restoring `match="retry may succeed"` after CodeRabbit recommended
removing it. The final decision is to keep the wording assertion removed: retry semantics are encoded
by `PostgresTransientOperationError`; English wording is not currently a repository-adapter public
contract. If wording becomes contractual, test it once at the connection/translation boundary.

---

## 5. Current CI state

The previous head `8c5da03cd4c996835cab7c531b0d3536a7cddb2d` completed all configured workflows successfully:

- CI;
- Python 3.11 / 3.12 / 3.13 deterministic tests;
- Ruff;
- strict MyPy;
- SQLFluff;
- GitHub Actions security audit;
- Security Regression;
- Dependency Review;
- Package validation;
- Mutation Testing workflow validation;
- PR Agent.

The current handoff head `61c67b491e8321098a933765a7faa93b5e9c45b7` includes additional review-driven test/docs/workflow
changes after that validated head. **Do not merge or declare PR #184 ready until the full latest-head
workflow set is confirmed green and review threads are checked again.**

---

## 6. Exact next actions

For the incoming agent:

1. Read `AGENTS.md`, this file, issue #185, and PR #184.
2. Confirm PR #184 still points at head `61c67b491e8321098a933765a7faa93b5e9c45b7` or note the newer head.
3. Inspect the latest CI workflow set for that exact head.
4. Inspect **all** top-level comments and inline review threads created after this handoff.
5. Apply/reply/resolve findings according to the `AGENTS.md` review contract.
6. If any code/test/workflow change is required, push it and repeat steps 3–5 on the new head.
7. When final-head checks and review triage are complete, refresh PR #184's body with the exact final
   head, test counts, and coverage results.
8. Leave a final PR handoff comment documenting readiness and the next issue (#185).
9. After #184 is merged, start issue #185 with the **interface/runtime boundary** slice:
   - `src/tarkka/interfaces/main.py`;
   - `src/tarkka/interfaces/cli.py`;
   - `src/tarkka/__main__.py`.
10. Bring that coherent slice to 100% branch coverage with behavior-focused tests, add a permanent CI
    subsystem ratchet, review every bot finding, and record the next handoff.

---

## 7. Issue #185 coverage program

Recommended order:

1. interface/runtime boundary;
2. core domain invariants;
3. security/network acquisition boundaries;
4. durable persistence adapters;
5. parser/provider adapters.

For each slice:

- changed executable lines remain 100% covered;
- selected subsystem reaches 100% **branch** coverage;
- add or expand a permanent `coverage report --fail-under=100` gate;
- do not add `pragma: no cover` or meaningless score-padding assertions;
- use property/contract/failure-injection/mutation testing where it improves confidence;
- keep live external services opt-in;
- run and review the final CI head;
- triage every automated reviewer comment before merge.

---

## 8. Repository navigation

Read progressively. Do not load every file at once.

Primary references for the immediate work:

- `AGENTS.md` — repository-wide coding/review/handoff contract;
- `docs/TESTING.md` — testing and coverage policy;
- `docs/ROADMAP.md` — implementation sequencing;
- `docs/AGENT_INTERFACE.md` and `docs/CONTEXT_EFFICIENCY.md` — MCP/agent design;
- issue #185 — historical coverage program;
- PR #184 — exact current implementation/review/CI record.

For the first #185 slice, then inspect:

- `src/tarkka/interfaces/main.py`;
- `src/tarkka/interfaces/cli.py`;
- `src/tarkka/__main__.py`;
- existing CLI/interface tests before creating new files.

Prefer extending existing test/support assets to creating parallel harnesses.

---

## 9. Handoff rule

This file is a **current snapshot**, not a historical journal. Replace stale status with the newest
checkpoint when handing work to another agent. Historical details already exist in Git commits,
issues, PRs, and review threads; do not let this file grow indefinitely.

Before ending substantial work, update:

- current branch/head;
- active PR/issue;
- latest validated CI state;
- review disposition state;
- exact next action.

That keeps the baton small, current, and useful.
