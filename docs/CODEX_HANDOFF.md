# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/security-robots-domain-coverage`
**Active PR:** #195 — `test: ratchet robots domain coverage to 100%`
**Active issue:** #189 — security/network acquisition coverage
**Parent program:** #185 — historical branch coverage to 100%

> `AGENTS.md` is authoritative. GitHub issues, pull requests, reviews, workflow runs, and commits are
> the historical audit trail. Always verify the live PR head because this handoff commit advances it.

## Current objective

Merge PR #195 after one final documentation-inclusive required-check/review sweep, then continue #189
from the resulting `main` in a fresh PR for robots/crawl application services. No user action is
currently required.

## Merged baseline

PR #194, the first #189 security-domain slice, merged into `main` as
`2c5f797272a3ac23be91c618bb524410be0bb653`.

Permanent inherited 100% gates include Phase 5 agent-serving, coverage tooling, interface/runtime,
thirteen core-domain modules, and the first #189 security/provenance modules.

## #195 validated source result

Validated source/test head before the CI-ratchet and handoff commits: `6768be9ea17ce69cdc1cc32cb6b0761df90df070`.

Python 3.13 result:

- **1,352 passed / 36 deselected**;
- repository aggregate: **12,285 statements / 838 misses; 3,870 branches / 626 partials = 91%**;
- `domain/crawl_access.py`: **75 statements + 32 branches = 100%**;
- `domain/robots_cache.py`: **53 + 24 = 100%**;
- `domain/robots_rules.py`: **179 + 70 = 100%**;
- completed robots-domain slice: **307 statements + 126 branches = 100%**;
- cumulative Phase 5 executable changed lines: **637/637 = 100%**;
- current PR executable changed lines: **2/2 = 100%**.

The same source head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, zizmor, Package, and
Dependency Review. The current CI ratchet extends `Enforce security domain coverage` to all six #189
completed domain modules: **641 statements + 234 branches**, required to remain at 100%.

## Production improvements made in #195

- Removed an unreachable inner UTF-8 guard from robots-rule pattern parsing; UTF-8 remains enforced once
  at the public `RobotsRules.parse()` boundary.
- `RobotsFetchResult` now rejects non-text content immediately for successful fetches, preventing invalid
  values from failing later inside cache/rules processing.

## Review disposition

All review threads present before this snapshot are resolved.

- The non-text successful robots-content finding was valid and fixed at the domain boundary.
- A pattern-matching semantics finding was verified as incorrect; existing expectations match the
  implementation (`/abc*bc$` does not disallow `/abc`; `/prefix*tail*$` intentionally matches a trailing
  arbitrary suffix and therefore disallows the tested target).
- The stale mixed-fixture invalid-UTF-8 finding was already fixed; the redundant unreachable production
  guard was removed rather than retained as artificial coverage debt.

Re-list reviews/threads on the live final head before merging because automated reviewers can add late
comments.

## Exact next actions

1. Read the live #195 head SHA.
2. Confirm required `main` ruleset checks on that exact head: `Quality`, Python 3.11, 3.12, and 3.13.
3. Confirm the expanded six-module #189 security-domain gate passes at **641 statements + 234 branches = 100%**.
4. Re-list review threads/submissions and disposition every meaningful late finding.
5. Refresh PR #195/#189 readiness metadata if needed and merge #195 using expected-head protection.
6. Keep #189 open; create a fresh branch from the #195 merge commit.

## Next #189 merge boundary

Target the robots/crawl application layer next:

- `application/crawl_eligibility.py`: baseline **80%**;
- `application/robots_refresh.py`: baseline **85%**;
- `application/recursive_crawl.py`: baseline **80%**.

Use deterministic fake fetch/cache/clock/transport boundaries for policy outcomes, refresh/reuse paths,
rate/budget guards, checkpoint/finalization recovery, and failure injection. Ratchet the completed set to
100% and merge before moving into `ports/http_transport.py` and
`infrastructure/web/pinned_http_transport.py`.

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: active
- #190 — durable persistence adapters: queued
- #191 — parser/provider/extraction adapters: queued

Issue #192 tracks native repository settings. Live state remains `delete_branch_on_merge=false`,
`allow_auto_merge=false`, and `allow_update_branch=false`. The connector does not expose repository
setting or branch-delete mutations, so use short-lived disposable branches and do not add a redundant
cleanup workflow; enable native merged-branch deletion through #192 when repository settings access is
available.
