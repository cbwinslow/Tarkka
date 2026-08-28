# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/security-http-transport-coverage`
**Active PR:** #197 — `test: harden HTTP transport and resolver coverage`
**Active issue:** #189 — security/network acquisition coverage
**Parent program:** #185 — historical branch coverage to 100%

> `AGENTS.md` is authoritative. GitHub issues, pull requests, reviews, workflow runs, and commits are
> the historical audit trail. Always verify the live PR head because this handoff commit advances it.

## Current objective

Merge PR #197 after one final documentation-inclusive required-check/review sweep, then continue #189
from the resulting `main` with a fresh HTTP acquisition/policy-fetch application PR. No user action is
currently required.

## Merged #189 baseline

- PR #194 merged as `2c5f797272a3ac23be91c618bb524410be0bb653`.
- PR #195 merged as `8ef51a637dffbb01bf6b5c5c23bc3ee26346488f`.
- PR #196 merged as `9771cd4405248eae6df45978d8b1664e6a5d085c`.
- Six completed security/robots domain modules are permanently protected at
  **641 statements + 234 branches = 100%**.
- Three completed crawl application modules are permanently protected at
  **305 statements + 120 branches = 100%**.

Inherited permanent 100% gates also protect Phase 5 agent-serving, coverage tooling,
interface/runtime, and the completed #188 core-domain invariant set.

## #197 validated source result

Validated source/test head immediately before the CI-ratchet and handoff commits:
`a0c69b15581d288d28cc6e0b66203f0625b7d60f`.

Python 3.13 result:

- **1,428 passed / 36 deselected**;
- repository aggregate: **12,281 statements / 771 misses; 3,862 branches / 573 partials = 91%**;
- `ports/http_transport.py`: **41 statements + 20 branches = 100%**;
- `infrastructure/web/pinned_http_transport.py`: **152 + 46 = 100%**;
- completed transport/resolver slice: **193 statements + 66 branches = 100%**;
- cumulative Phase 5 executable changed lines: **652/652 = 100%**;
- current PR executable changed source lines: **12/12 = 100%**.

The same source head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, zizmor, and every
inherited coverage ratchet. A new `Enforce HTTP transport coverage` CI gate now permanently protects
the completed pair at 100%.

## Boundary defects and cleanup in #197

Coverage-driven contract testing found and fixed a real exception-boundary defect:

- invalid IDNA origin hostnames could leak a raw Unicode codec exception;
- `PinnedHttpTransport.request()` now translates that failure to Tarkka's stable HTTP URI `ValueError`
  boundary with the codec error chained as the cause.

The pass also clarified an important HTTP contract: an empty field value is valid transport data and
must be preserved so the application layer can reject an unusable empty redirect `Location`. The
transport therefore preserves `("",)` while rejecting empty value sequences, non-string values, and
CR/LF injection.

Coverage analysis removed two unreachable defensive states instead of excluding them:

- the resolver result queue now represents exactly one successful address tuple or one exception,
  eliminating an impossible `(None, None)` result;
- `_read_limited()` no longer checks a sentinel that is mathematically positive under its loop
  invariant.

A deterministic fake HTTPS connection now covers pinned HTTPS construction and request routing without
DNS or socket I/O. Timed hostname resolution success is covered explicitly, including canonical unique
IPv4/IPv6 output.

## Exact next actions

1. Read the live #197 head SHA; this handoff commit is newer than the validated source head.
2. Confirm required `main` ruleset checks on that exact head: `Quality`, Python 3.11, 3.12, and 3.13.
3. Confirm `Enforce HTTP transport coverage` reports **193 statements + 66 branches = 100%**.
4. Confirm inherited #189 domain/application gates remain **641 + 234** and **305 + 120**, both 100%.
5. Re-list inline review threads and submitted reviews; fix or disposition every meaningful late finding.
6. Update PR #197 / issue #189 with final exact-head readiness and merge using expected-head SHA
   protection.
7. Keep #189 open and create the next branch from the #197 merge SHA.

## Next #189 merge boundary

Target the HTTP acquisition/policy-fetch application services next:

- `application/http_acquisition.py`: **251 statements + 86 branches, currently 82%**;
- `application/http_policy_fetch.py`: **142 statements + 32 branches, currently 84%**.

Current coverage debt is concentrated in constructor/argument validation, traversal-budget and pacing
boundaries, redirect/finalization paths, resolver/transport failure translation, response-overflow and
artifact/finalization recovery. Prefer deterministic fake resolver/transport/repository tests and
failure injection; no live network access in the default suite. Ratchet the completed pair to 100%
before considering #189 complete or moving to #190.

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
