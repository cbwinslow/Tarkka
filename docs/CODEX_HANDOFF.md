# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/core-domain-coverage-ratchet`
**Active PR:** #193 — `test: ratchet core domain invariant coverage to 100%`
**Active issue:** #188 — core domain invariant coverage
**Parent program:** #185 — historical branch coverage to 100%
**Next issue after merge:** #189 — security/network acquisition coverage

> `AGENTS.md` is authoritative. This file is the current execution baton, not a journal. GitHub issues,
> pull requests, reviews, workflow runs, and commits are the historical audit trail. Always verify the
> live PR head because the commit updating this file necessarily advances the branch.

---

## 1. Current objective

Finish #188 by validating and merging PR #193, then start #189 immediately from the resulting `main`.

The #188 pure/core-domain slice is functionally complete. The permanent CI step **Enforce core domain
invariant coverage** protects these modules at 100% branch coverage:

- `src/tarkka/domain/bibliography.py`
- `src/tarkka/domain/citations.py`
- `src/tarkka/domain/discovery.py`
- `src/tarkka/domain/identity_candidates.py`
- `src/tarkka/domain/media_types.py`
- `src/tarkka/domain/models.py`
- `src/tarkka/domain/policy_requests.py`
- `src/tarkka/domain/rights_access.py`
- `src/tarkka/domain/source_artifacts.py`
- `src/tarkka/domain/source_observations.py`
- `src/tarkka/domain/traversal.py`
- `src/tarkka/domain/verification.py`
- `src/tarkka/domain/work_identity.py`

No coverage exclusions or production-score padding were introduced.

---

## 2. Merged baseline

PR #186 / issue #187 completed the interface/runtime slice and merged into `main` as:

`90ed54e471188f4b0be2251cd7a295d2a7365849`

Permanent inherited coverage invariants on `main` before #193:

- `src/tarkka/__main__.py`, `src/tarkka/interfaces/cli.py`, and
  `src/tarkka/interfaces/main.py` remain 100% branch-covered;
- Phase 5 agent-serving/context-package/telemetry modules remain 100%;
- `scripts/check_diff_coverage.py` remains 100%;
- cumulative Phase 5 executable changes from immutable anchor
  `7e4f51ddb14a44c1b32a782d3cbdbb7c06a41b01` remain 100%;
- changed executable Python lines are required to be 100% covered.

PR #193 starts cleanly from that exact merge commit.

---

## 3. Latest validated #188 measurement

Validated head before the final ratchet/mutation/handoff commits:

`9588a5740576f9a4be1efeeb04ebc35b4d622305`

Python 3.13 result:

- **1,289 passed / 36 deselected**;
- repository aggregate: **12,277 statements / 901 misses; 3,870 branches / 669 partials = 90%**;
- `domain/bibliography.py`: **51 statements + 14 branches = 100%**;
- `domain/citations.py`: **153 + 66 = 100%**;
- `domain/discovery.py`: **89 + 14 = 100%**;
- `domain/identity_candidates.py`: **79 + 36 = 100%**;
- `domain/media_types.py`: **16 + 8 = 100%**;
- `domain/models.py`: **139 + 52 = 100%**;
- `domain/policy_requests.py`: **29 + 16 = 100%**;
- `domain/rights_access.py`: **50 + 20 = 100%**;
- `domain/source_artifacts.py`: **93 + 36 = 100%**;
- `domain/source_observations.py`: **151 + 32 = 100%**;
- `domain/traversal.py`: **234 + 102 = 100%**;
- `domain/verification.py`: **44 + 16 = 100%**;
- `domain/work_identity.py`: **30 + 4 = 100%**.

The same head passed Python 3.11/3.12/3.13, Ruff, strict mypy, SQLFluff, zizmor, the inherited Phase 5
and interface/runtime gates, and 617/617 cumulative Phase 5 changed-line coverage.

The current branch is newer than this validated measurement because later commits completed the
13-module permanent ratchet, extended mutation configuration, and refreshed this handoff. Revalidate
the live head before merging.

---

## 4. Test strategy added in #193

The new tests protect actual domain behavior rather than merely exercising lines:

- immutable mapping/value-object contracts for Workspace, Work, Acquisition, discovery, and source
  observations;
- source artifact ordinals/page/label/range validation;
- identity-candidate evidence/index/review invariants;
- evidence-relation exact-evidence and `NO_EVIDENCE` semantics;
- rights decisions and explicit resource-use semantics;
- policy-request budget accounting and elapsed-time monotonicity;
- citation mention/context/resolution/work-relation invariants;
- bibliography source identity and format-specific publication mapping;
- discovery query/provider/cursor/year validation;
- traversal target/checkpoint construction, provenance, deduplication, eligibility, request/byte
  accounting, finalization, recovery, retry, failure, and skip transitions.

Traversal hardening intentionally complements the existing Hypothesis lifecycle state machine instead of
replacing it with duplicated example tests.

---

## 5. Mutation testing

`pyproject.toml` now preserves the existing mutmut targets and adds the highest-risk completed #188
state machine:

- `src/tarkka/domain/identifiers.py`
- `src/tarkka/domain/traversal.py`
- `src/tarkka/infrastructure/storage/parser_identity.py`

The selected mutation tests are bounded to identifier/parser identity plus traversal budget,
checkpoint, finalization, invariant, and property tests.

PR-side **Mutation Testing / Validate mutation tooling** passed on source head
`f5ef4fd7b270ae17792a0935a4ebc35077053774`. The expensive targeted mutation baseline is deliberately
not run on every PR; `.github/workflows/mutation-testing.yml` runs it on the weekly schedule or manual
workflow dispatch. Do not claim an actual mutation-score result until such a run is observed.

---

## 6. Review status

Two substantive CodeRabbit findings were dispositioned:

1. Citation range-length mismatch coverage — declined as duplicate after verifying existing
   `tests/test_citation_contracts.py` already covers both mention and context mismatch branches;
   CodeRabbit independently verified this and withdrew the finding.
2. Capability-manifest blank media type — implemented by separating the blank-string case from the
   non-string-member case.

Both inline threads are resolved. The stale CodeRabbit `CHANGES_REQUESTED` review from old head
`26bdb6216e1d708b6313fc13512e8dfb95543169` was dismissed after both findings were resolved/withdrawn.
Re-sweep the final live head because bots can add new comments after this snapshot.

---

## 7. Exact next actions

1. Read the live #193 head SHA; this handoff commit advances it beyond the SHAs above.
2. Confirm final-head workflows:
   - Python 3.11 / 3.12 / 3.13;
   - Ruff / strict mypy / SQLFluff / zizmor;
   - Phase 5 subsystem = 100%;
   - interface/runtime = 100%;
   - **13-module core-domain ratchet = 100%**;
   - cumulative Phase 5 diff = 617/617;
   - Mutation Testing tooling validation succeeds;
   - Package, PostgreSQL repository checks, Dependency Review, Docling, PR-Agent, and other triggered
     workflows are green.
3. Re-list inline review threads and submitted reviews. Resolve or explicitly disposition every new
   substantive finding.
4. Update PR #193 and #188/#185 with exact final-head metrics/readiness.
5. Merge #193 with expected-head SHA protection when branch rules allow it.
6. Close #188 completed and update #185 to make #189 active.
7. Create `test/security-network-coverage-ratchet` from the new merge SHA and open the #189 PR.

---

## 8. #189 prepared starting point

The latest coverage measurement puts the next security/network targets at:

- `domain/resource_acquisition.py`: **93%** — remaining lines 63, 67-68, 84-85, 172, 181, 193-194;
- `domain/http_observations.py`: **93%** — 107, 113-114, 132-133, 196, 271-272, 289, 292, 312-313;
- `domain/policy_fetch_finalization.py`: **74%** — 12, 40, 46, 52, 54, 60;
- `domain/crawl_access.py`: **81%**;
- `domain/robots_cache.py`: **82%**;
- `domain/robots_rules.py`: **87%**;
- `application/http_acquisition.py`: **82%**;
- `application/http_policy_fetch.py`: **84%**;
- `application/recursive_crawl.py`: **80%**;
- `application/crawl_eligibility.py`: **80%**;
- `application/robots_refresh.py`: **85%**;
- `infrastructure/web/pinned_http_transport.py`: **89%**;
- `ports/http_transport.py`: **67%**.

Start #189 with the compact validation/provenance-heavy domain modules
`resource_acquisition.py`, `http_observations.py`, and `policy_fetch_finalization.py`, permanently
ratchet each completed set, then move outward into robots/crawl and the HTTP transport/application
boundaries. Favor adversarial/property/failure-injection tests for SSRF, DNS/address policy, redirect,
budget, and provenance behavior.

---

## 9. Remaining program

Coverage children:

- #187 — interface/runtime (**completed / merged**)
- #188 — core domain invariants (**final merge candidate**)
- #189 — security/network acquisition (**next**)
- #190 — durable persistence adapters
- #191 — parser/provider/extraction adapters

Parent #185 remains open until repository-wide deterministic branch coverage reaches 100% without
artificial exclusions.

Repository automation issue #192 remains separate and tracks GitHub-native security/settings work.
