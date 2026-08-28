# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/phase5-coverage-hardening`
**Active PR:** #184 — `test: harden Phase 5 coverage and scheduled security CI`
**Canonical follow-up:** #185 — `test: ratchet historical branch coverage from 86% to 100%`

> This is the current execution snapshot for any coding agent, despite the historical filename.
> `AGENTS.md` remains authoritative. Read it first, then this handoff, then the canonical issue/PR.
> The PR's current GitHub head is authoritative; the commit that updates this file necessarily advances
> the branch beyond any source-head SHA mentioned while preparing the snapshot.

---

## 1. Current objective

Finish PR #184 to a fully reviewed, fully green final head, then continue issue #185 by raising
historical branch coverage to 100% one coherent subsystem at a time.

Immediate rules:

- preserve Tarkka's architecture/provenance contracts;
- require 100% coverage for new/modified executable Python source and repository tooling;
- permanently ratchet completed subsystems/tooling to 100% branch coverage;
- review every automated-review finding and reply with an explicit disposition;
- keep this snapshot plus the canonical GitHub issue/PR sufficient for another agent to resume.

---

## 2. PR #184 scope and completed work

PR #184 took over the Codex Phase 5 sequence from PRs #176–#183 and hardened it.

Implemented/fixed:

- repaired scheduled Security Regression collection by installing the optional MCP extra in that CI
  profile;
- kept MCP tests safely skippable when the optional extra is genuinely absent;
- raised changed-line coverage from 80% to 100% and made 100% the checker default;
- made diff-coverage failures print exact uncovered source lines;
- added a permanent 100% branch-coverage gate for the Phase 5
  agent-serving/context-package/telemetry subsystem;
- added a cumulative 100% changed-line gate from the immutable pre-Phase-5 anchor;
- made optional MCP telemetry-recorder failures non-fatal to research operations while emitting a
  DEBUG diagnostic with exception context;
- expanded context-package, PostgreSQL, MCP, CLI, telemetry, capability-schema, and persistence
  failure-path tests;
- documented the 100% coverage ratchet in `docs/TESTING.md`;
- added explicit reviewer-triage and AI-handoff contracts to `AGENTS.md`;
- replaced the stale historical handoff with this current-snapshot model.

Latest reviewer-driven coverage-policy hardening:

- CodeRabbit correctly identified that the written “every executable source line” policy was broader
  than enforcement, because `scripts/` was outside `scripts/check_diff_coverage.py`'s scope;
- enforcement was strengthened rather than documentation weakened:
  - `scripts/check_diff_coverage.py` now tracks both `src/tarkka/` and Python under `scripts/`;
  - CI coverage collection now includes both `--cov=tarkka` and `--cov=scripts`;
  - `scripts/check_diff_coverage.py` has its own permanent `--fail-under=100` coverage gate;
  - `tests/test_diff_coverage.py` now exercises script-path normalization, Git path scoping, CLI
    success/failure/error handling, threshold validation, diagnostics, and the executable entrypoint.

The source head immediately before this snapshot update was
`7f97601f420a01c97876e2d5b01c492ddb074f82`; verify the PR head in GitHub because this documentation
commit advances it.

---

## 3. Last fully validated baseline

Before the latest `scripts/` coverage-scope strengthening, exact head
`aefa621c6b2b9f0bd9ec8a23b09e5cc2fa18168b` completed deterministic CI successfully:

- Python 3.11: pass;
- Python 3.12: pass;
- Python 3.13: **1,021 passed, 36 deselected**;
- Ruff: pass;
- strict mypy: pass;
- SQLFluff: pass;
- GitHub Actions security audit: pass;
- Security Regression: pass;
- Dependency Review: pass;
- Package validation: pass;
- Mutation Testing workflow validation: pass.

Coverage at that validated head:

- repository: **11,938 statements, 1,219 misses, 3,746 branches, 829 partials = ~86%**;
- Phase 5 agent-serving subsystem: **549 statements, 0 misses, 122 branches, 0 partials = 100%**;
- cumulative Phase 5 executable diff: **583/583 = 100%**.

The current head includes the later `scripts/` coverage-policy hardening. **Do not merge or declare
#184 ready until the exact current head passes the full workflow set and review threads are checked
again.**

---

## 4. Automated review contract/status

Follow the process in `AGENTS.md` after every meaningful push.

All substantive review threads that existed before the latest coverage-policy hardening were reviewed,
replied to, and resolved. Important decisions:

### Applied

- telemetry-recorder failure logging;
- maintainable Phase 5 coverage include configuration;
- PostgreSQL connection cleanup after post-acquisition failure;
- removal of brittle repository-level error-message matching;
- existing-but-non-callable capability-registration coverage;
- typed telemetry test overrides;
- explicit non-POSIX fsync no-op assertion;
- clearer structured MCP test helper semantics;
- broader coverage enforcement for repository Python scripts/tooling.

### Intentionally retained

- broad `except Exception` around **only** `telemetry.record(event)`: optional observability cannot
  change research results; Tarkka event construction stays outside the boundary and recorder failures
  are logged/tested;
- immutable pre-Phase-5 commit SHA: a movable ref could silently weaken the historical ratchet;
- cumulative gate on pushes to `main`: it is a permanent post-merge invariant, not only a PR check;
- dated 86% baseline in `docs/TESTING.md`: it is an auditable historical measurement;
- CLI `capsys.readouterr()` loop: each iteration calls `main(command)` before reading/clearing fresh
  stderr, so the review claim that later iterations see no output was incorrect;
- no duplicate invalid-section-ID test in the focused MCP file because those cases already exist in
  the main MCP suite and MCP is at 100% branch coverage;
- no repository-level assertion on the exact phrase `retry may succeed`: retry semantics are encoded
  by `PostgresTransientOperationError`; English wording is not a stable adapter contract.

Re-check all top-level and inline comments after the latest CI run; bots may add new findings.

---

## 5. Exact next actions for the incoming agent

1. Read `AGENTS.md`, this file, PR #184, and issue #185.
2. Read the current PR #184 head SHA from GitHub.
3. Inspect the full workflow set for **that exact head**.
4. In particular confirm:
   - Python 3.11/3.12/3.13 tests;
   - Ruff/mypy/SQLFluff/zizmor;
   - Phase 5 subsystem coverage = 100%;
   - `scripts/check_diff_coverage.py` tooling coverage = 100%;
   - cumulative Phase 5 diff coverage = 100%;
   - current-PR changed-line coverage = 100%;
   - Security Regression, Dependency Review, Package, Mutation Testing, and PR Agent status.
5. Inspect all new top-level and inline bot comments created after this snapshot.
6. Apply/reply/resolve findings according to `AGENTS.md`; if any repository change is needed, repeat
   steps 2–5 on the new head.
7. Once the final head is green and review-clean, update PR #184's body with exact final test/coverage
   numbers and leave a top-level readiness/handoff comment. Metadata/comments do not change the head.
8. Leave merging #184 to the repository owner unless explicitly instructed otherwise.
9. Continue issue #185 on a separate branch based on the final #184 head (stacked until #184 merges).

---

## 6. Issue #185 first slice: interface/runtime coverage

Start with:

- `src/tarkka/__main__.py` — last measured **0%**;
- `src/tarkka/interfaces/cli.py` — last measured **68%**;
- `src/tarkka/interfaces/main.py` — last measured **80%**.

At the last coverage report, the largest uncovered interface regions were concentrated in command
construction/dispatch, environment/backend selection, parser/error paths, and runtime wiring. Inspect
existing tests before creating new files; prefer extending reusable helpers and behavior-focused tests.

Acceptance criteria for the slice:

- all new/modified executable Python lines remain 100% covered;
- the three interface/runtime modules reach 100% **branch** coverage;
- add a permanent CI `--fail-under=100` gate for the completed slice;
- no artificial exclusions or score-padding assertions;
- supported Python matrix/static/security checks remain green;
- all bot comments are reviewed/replied/resolved on the final stacked-PR head.

After this slice, issue #185's recommended sequence is:

1. core domain invariants;
2. security/network acquisition boundaries;
3. durable persistence adapters;
4. parser/provider adapters.

---

## 7. Handoff maintenance rule

This file is a **current snapshot, not a journal**. Replace stale status instead of appending session
history. Git commits, issues, PRs, and review threads are the historical audit trail.

Before handing off substantial work, refresh only what another agent needs to resume:

- active issue/PR/branch;
- latest validated CI/coverage state;
- important reviewer decisions;
- unresolved blockers;
- exact next action.
