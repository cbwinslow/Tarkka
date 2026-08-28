# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/security-crawl-application-coverage`
**Active PR:** #196 — `test: harden crawl application coverage`
**Active issue:** #189 — security/network acquisition coverage
**Parent program:** #185 — historical branch coverage to 100%

> `AGENTS.md` is authoritative. GitHub issues, pull requests, reviews, workflow runs, and commits are
> the historical audit trail. Always verify the live PR head because this handoff commit advances it.

## Current objective

Merge PR #196 after the final documentation-inclusive required-check/review sweep, then continue #189
from the resulting `main` with a fresh HTTP transport/resolver coverage PR. No user action is currently
required.

## Merged #189 baseline

- PR #194 merged as `2c5f797272a3ac23be91c618bb524410be0bb653` and completed the first HTTP
  observation/policy-finalization/resource-acquisition domain slice.
- PR #195 merged as `8ef51a637dffbb01bf6b5c5c23bc3ee26346488f` and completed crawl access,
  robots cache, and robots rules.
- The permanent #189 domain gate protects six modules: **641 statements + 234 branches = 100%**.

Inherited permanent 100% gates also protect Phase 5 agent-serving, coverage tooling, interface/runtime,
and the completed #188 core-domain invariant set.

## #196 validated source result

Validated source/test head before the CI-ratchet and handoff commits: `b1a0a9bd44b614ad184a2ce6592894e78b156179`.

Python 3.13 result:

- **1,367 passed / 36 deselected**;
- repository aggregate: **12,282 statements / 798 misses; 3,866 branches / 587 partials = 91%**;
- `application/crawl_eligibility.py`: **47 statements + 22 branches = 100%**;
- `application/robots_refresh.py`: **96 + 30 = 100%**;
- `application/recursive_crawl.py`: **162 + 68 = 100%**;
- completed application slice: **305 statements + 120 branches = 100%**;
- cumulative Phase 5 executable changed lines: **640/640 = 100%**;
- current PR executable changed source lines: **3/3 = 100%**.

The same source head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, zizmor, and every
inherited coverage ratchet. A new `Enforce security application coverage` CI gate now permanently
protects the three #196 application modules at 100%.

## Production cleanup in #196

Coverage analysis identified two coordinator guards that duplicated invariants already enforced by
`RecursiveCrawlGateResult` construction:

- `ROBOTS_REFRESH_REQUIRED` always has a robots URI;
- `READY` always has an effective acquisition policy.

Those unreachable duplicate branches were removed instead of being excluded or covered through
corrupted frozen dataclass state. The coordinator now uses typed casts after status checks and relies on
the validated result contract. A separate reachable invariant—attaching a real acquisition to a
non-READY gate—remains enforced and is explicitly tested.

## Exact next actions

1. Read the live #196 head SHA; this handoff commit is newer than the validated source head.
2. Confirm required `main` ruleset checks on that exact head: `Quality`, Python 3.11, 3.12, and 3.13.
3. Confirm `Enforce security application coverage` reports **305 statements + 120 branches = 100%**.
4. Confirm the inherited six-module security-domain gate remains **641 + 234 = 100%**.
5. Re-list inline review threads and submitted reviews; fix or disposition every meaningful late finding.
6. Update PR #196 / issue #189 with final exact-head readiness and merge using expected-head SHA
   protection.
7. Keep #189 open and create the next fresh branch from the #196 merge SHA.

## Next #189 merge boundary

Target the HTTP transport/resolver boundary next:

- `ports/http_transport.py`: current coverage **67%**;
- `infrastructure/web/pinned_http_transport.py`: current coverage **89%**.

Focus on response-contract validation, resolver timeout/error/no-result paths, address canonicalization,
TLS socket cleanup, request URI/timeout validation, header grouping, byte-limit/deadline behavior, and
pinned connection semantics. Prefer deterministic monkeypatch/fake socket/response tests; no live network
access in the default suite. Ratchet the completed pair to 100% before moving into
`application/http_acquisition.py` (**82%**) and `application/http_policy_fetch.py` (**84%**).

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: active
- #190 — durable persistence adapters: queued
- #191 — parser/provider/extraction adapters: queued

Issue #192 tracks native repository settings. Live state remains `delete_branch_on_merge=false`,
`allow_auto_merge=false`, and `allow_update_branch=false`. The connector does not expose repository
setting or branch-delete mutations, so continue using short-lived disposable branches and do not add a
redundant cleanup workflow; enable native merged-branch deletion through #192 when repository settings
access is available.
