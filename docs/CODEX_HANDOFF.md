# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/interface-runtime-coverage-ratchet`
**Active PR:** #186 — `test: ratchet interface runtime coverage to 100%`
**Active issue:** #187 — interface/runtime coverage slice
**Parent program:** #185 — historical branch coverage to 100%
**Next issue after merge:** #188 — core domain invariant coverage

> `AGENTS.md` is authoritative. This file is the current execution baton, not a journal. GitHub issues,
> pull requests, reviews, workflow runs, and commits are the historical audit trail. Always verify the
> live PR head because the commit updating this file necessarily advances the branch.

---

## 1. Current objective

Close #187 by merging PR #186 after one final exact-head CI/review sweep, then start #188 from the new
`main` immediately.

The interface/runtime slice is functionally complete and has reached 100% branch coverage:

- `src/tarkka/__main__.py`
- `src/tarkka/interfaces/cli.py`
- `src/tarkka/interfaces/main.py`

The CI workflow now permanently enforces all three together with `coverage report --fail-under=100`.

Rules remain:

- no coverage exclusions or score-padding assertions;
- deterministic/network-free default tests;
- preserve CLI/API behavior unless a real defect is demonstrated;
- verify, reply to, and resolve every substantive automated-review finding;
- merge only an exact head that satisfies branch rules and configured checks.

---

## 2. Merged baseline

PR #184 merged into `main` as `a2e601118ca6b1ad3e756324a809d7300c959372`.

Permanent invariants inherited from #184:

- every changed executable Python line under `src/tarkka/` and `scripts/` must be covered;
- cumulative Phase 5 changes from immutable anchor
  `7e4f51ddb14a44c1b32a782d3cbdbb7c06a41b01` remain 100% covered;
- Phase 5 agent-serving/context-package/telemetry modules remain 100% branch-covered;
- `scripts/check_diff_coverage.py` remains 100% branch-covered;
- bot-review triage and cross-agent handoff rules are defined in `AGENTS.md`.

PR #186 was rebuilt cleanly from this merge commit after #184 landed. Do not reintroduce its old
stacked ancestry.

---

## 3. #187 result

Validated source head immediately before the final CI-ratchet commit:

`df5904bef23b939d5b5eb6fbeaf2e769ddbe1c22`

Exact Python 3.13 result:

- **1,112 passed / 36 deselected**;
- repository aggregate: **12,277 statements / 1,039 misses; 3,870 branches / 804 partials = 88%**;
- `src/tarkka/__main__.py`: **2 statements, 0 misses = 100%**;
- `src/tarkka/interfaces/cli.py`: **278 statements, 46 branches, 0 misses/partials = 100%**;
- `src/tarkka/interfaces/main.py`: **733 statements, 122 branches, 0 misses/partials = 100%**;
- inherited Phase 5 subsystem: **549 statements + 122 branches = 100%**;
- coverage checker: **154 statements + 70 branches = 100%**;
- cumulative Phase 5 executable diff: **617/617 = 100%**.

The same exact head passed:

- Python 3.11;
- Python 3.12;
- Python 3.13;
- Ruff;
- strict mypy;
- SQLFluff;
- zizmor GitHub Actions audit.

The following commit then promoted the completed slice into a permanent CI invariant:

`759419e36910738f6fb386deb43dc60a28282ed2` — `ci: ratchet full interface runtime coverage`

Its CI step is named **Enforce interface runtime coverage** and includes all three target modules.

---

## 4. What PR #186 added

Behavior-focused tests now protect:

- package and script entrypoint dispatch;
- backend and environment configuration;
- optional parser/provider construction and provider credential forwarding;
- UUID/handle parsing and provider policy/cursor validation;
- Work payload null/empty and populated shapes;
- ingest/discovery/work/inspect/read success and stable error contracts;
- full-text acquisition dependency wiring;
- database-upgrade serialization/error translation;
- identity suggestion/decision serialization and failures;
- rule/model claim-extraction metadata contracts;
- generalized evidence payload variants and fallback behavior;
- claim list/show filtering and repository failures;
- citation/resource pagination and missing-state boundaries;
- verification record/list/show/candidate failures and evidence-only expansion;
- source-observation summary provenance;
- bibliography/legacy routing and real module execution;
- top-level identity parser and dispatch.

The test strategy intentionally verifies observable contracts and dependency wiring rather than merely
executing uncovered lines.

---

## 5. Review status / decisions

All substantive inline findings seen before this snapshot were dispositioned with commit-backed replies
and resolved. Reviewer-driven improvements included:

- complete `ResearchQuery` argument-forwarding assertions;
- exact `FullTextAcquisitionService` dependency graph assertions;
- discovery provider environment/credential forwarding;
- deterministic removal of inherited `TARKKA_WORK_BACKEND` in the script-entrypoint test;
- null/empty Work payload coverage;
- model extractor optional-default coverage;
- successful `rationale=None` identity decisions;
- rule-extractor payloads without model metadata;
- realistic `Hypothesis` records for non-Claim filtering;
- Ruff formatting fixes.

A late Kilo question about the removed `char_end` expectation was verified against production code and
resolved: passage evidence intentionally exposes `passage_char_start` / `passage_char_end`; there is no
redundant `char_end` alias.

Re-list inline threads and submitted reviews on the final live head before merging because bots can add
new comments after this snapshot.

---

## 6. Exact next actions

1. Read the live #186 head SHA. This documentation commit is newer than the source/CI-ratchet SHAs
   quoted above.
2. Confirm final-head CI:
   - Python 3.11 / 3.12 / 3.13;
   - Ruff / strict mypy / SQLFluff / zizmor;
   - Phase 5 subsystem = 100%;
   - coverage checker = 100%;
   - **full interface/runtime gate = 100%**;
   - cumulative Phase 5 diff = 617/617;
   - current-PR changed executable lines = 100%;
   - Dependency Review and all other workflows actually triggered on the head.
3. Re-list all top-level comments, inline review threads, and review submissions. Apply or explicitly
   decline findings with evidence; resolve every substantive thread.
4. Update PR #186 body and #187/#185 with exact final-head metrics and readiness state.
5. Leave a final merge-readiness comment.
6. Merge #186 to `main` using expected-head SHA protection once branch rules allow it.
7. Close #187 as completed and update #185 to point at #188.
8. Create a fresh #188 branch from the new `main` and open its PR before doing core-domain work.

---

## 7. #188 prepared starting point

Issue #188 targets pure/core domain invariant coverage. Current coverage hotspots from the #187 final
measurement include:

- `domain/identity_candidates.py`: **70%** — 17 missed statements / 17 partial branches;
- `domain/source_artifacts.py`: **72%** — 18 missed / 18 partials;
- `domain/verification.py`: **77%** — 7 missed / 7 partials;
- `domain/traversal.py`: **77%** — 39 missed / 39 partials;
- `domain/models.py`: **81%** — 19 missed / 16 partials;
- `domain/rights_access.py`: **83%**;
- `domain/citations.py`: **90%**.

Recommended first #188 batch: close the compact invariant-heavy value objects before tackling the much
larger traversal state machine. Start with `identity_candidates.py`, `source_artifacts.py`, and
`verification.py`; use parametrized/property tests for validation boundaries, then permanently ratchet
completed coherent modules to 100%. After the domain slice reaches 100%, run targeted mutation testing
to verify assertion quality as required by #188.

---

## 8. Broader roadmap / GitHub automation

Coverage child issues:

- #187 — interface/runtime (**merge candidate**)
- #188 — core domain invariants (**next**)
- #189 — security/network acquisition
- #190 — durable persistence adapters
- #191 — parser/provider/extraction adapters

Repository automation issue #192 tracks GitHub-native settings/security features: verify CodeQL default
setup and secret-scanning/push-protection state, enable delete-merged-branches, and evaluate auto-merge
and update-branch support. Do not add a duplicate CodeQL workflow or another generic AI reviewer.

Release/PyPI SBOM/provenance attestations remain deferred until release policy is finalized.
