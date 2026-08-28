# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/security-full-text-http-coverage`
**Active PR:** #200 — `test: ratchet full-text HTTP coverage to 100%`
**Active issue:** #189 — security/network acquisition coverage
**Parent program:** #185 — historical branch coverage to 100%
**Product roadmap:** #198 — auditable/replayable research differentiation

> `AGENTS.md` is authoritative. GitHub issues, pull requests, review threads, workflow runs, and
> commits are the historical audit trail. Always re-read the live PR head because this handoff update
> advances it.

## Current objective

Finish and merge PR #200 with expected-head protection after validating the new permanent CI ratchets
and completing the final reviewer sweep. PR #200 is intended to complete issue #189. After merge,
close #189 and continue directly into #190 durable persistence adapters.

No user action is required for routine PR merging.

## Recently merged #189 work

- PR #194 merged as `2c5f797272a3ac23be91c618bb524410be0bb653`.
- PR #195 merged as `8ef51a637dffbb01bf6b5c5c23bc3ee26346488f`.
- PR #196 merged as `9771cd4405248eae6df45978d8b1664e6a5d085c`.
- PR #197 merged as `7eca7c077e474b0b63580d10522d2393eaa88e4a`.
- PR #199 merged as `7ddd684d0127a17db85005d37fcc94c4f45b1385`.

Permanent 100% gates inherited by #200 before its final ratchet:

- security/robots domain: **641 statements + 234 branches = 100%**;
- security application after #199: **693 statements + 232 branches = 100%**;
- HTTP resolver/transport boundary after #197: **193 statements + 66 branches = 100%**;
- Phase 5 agent-serving, coverage tooling, interface/runtime, and #188 core-domain invariants are also
  permanently protected at 100%.

## #200 latest fully validated source result

Latest fully validated source head before the permanent-gate/handoff commits:
`f2f423e33284bf8603c31ddf7c6b11b0aa26ed1a`.

Python 3.13 result:

- **1,531 passed / 36 deselected**;
- repository aggregate: **12,273 statements / 694 misses; 3,854 branches / 515 partials = 92%**;
- `application/full_text.py`: **42 statements + 6 branches = 100%**;
- `infrastructure/full_text/http.py`: **136 statements + 58 branches = 100%**;
- completed full-text pair: **178 statements + 64 branches = 100%**;
- cumulative Phase 5 executable changed lines: **657/657 = 100%**;
- current PR changed executable source lines on that head: **1/1 = 100%**.

The same head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, and zizmor. Package and
Dependency Review also passed. Recheck PR Agent on the live head before merge.

Commit `cb4db2ba5180d3f588fec944e9e895a3d850d692` extends the permanent gates so:

- `Enforce security application coverage` now includes `src/tarkka/application/full_text.py`;
- `Enforce HTTP transport coverage` now includes `src/tarkka/infrastructure/full_text/http.py`.

Expected gate totals after that commit are **735 statements + 238 branches = 100%** for security
application and **329 statements + 124 branches = 100%** for HTTP transport. These are predictions
until the documentation-inclusive live head validates them in CI.

## #200 behavior and test hardening

`tests/test_full_text_application_hardening.py` covers:

- constructor rejection when no full-text resolver is configured;
- unknown Work rejection before resolver/fetch activity;
- deterministic `FullTextNotFoundError` when all resolvers miss.

`tests/test_full_text_http_hardening.py` covers the bounded full-text adapter without live network I/O:

- constructor timeout/max-byte/user-agent validation;
- exact hostname, public resolved address, byte cap, and decreasing deadline propagation;
- stale/partial destination cleanup on failure;
- explicit transport size-limit signaling;
- redirect Location validation, same-origin enforcement, port changes, and redirect count limits;
- non-success HTTP status and empty-success-body failures;
- deadline exhaustion before and after DNS;
- exhausted byte caps and private/disallowed resolved addresses;
- malformed/hostless URI helpers;
- duplicate/blank/whitespace/control/percent-encoded-control/unsafe-scheme/invalid-authority redirects;
- Content-Type and Content-Length cardinality, parsing, mismatch, and oversize contracts.

The first hardening pass took `infrastructure/full_text/http.py` directly from 79% to 100%.
`application/full_text.py` reached 96% with one remaining branch, which was then removed as duplicate
state validation rather than reached by constructing an invalid domain object.

## Production simplification justified by invariant

`FullTextResource.__post_init__` is the authoritative filename safety contract. It requires a nonblank
filename that is exactly one non-traversing POSIX/Windows path component, rejects `.`/`..`, path
separators, and backslashes, and also validates the HTTPS source URI. Therefore the acquisition
orchestrator's second `path.parent != root` escape check was unreachable through a valid
`FullTextResource` and was removed. The service now joins the validated filename directly beneath its
fresh temporary directory.

## Review-bot status

As of source head `f2f423e...`:

- no inline review threads had been emitted;
- Qodo is paused because its subscription is inactive;
- CodeRabbit was temporarily rate-limited and emitted no actionable finding;
- CodeAnt had started review but had not emitted inline findings at the last sweep.

This is not final. After the CI/handoff commits, re-list all inline review threads and top-level bot
comments. Verify, reply to, and resolve every substantive new finding according to `AGENTS.md`.

## Exact next actions

1. Read live PR #200 head SHA after this handoff commit.
2. Confirm Python 3.11/3.12/3.13, Quality, Package, Dependency Review, and PR Agent on that exact head.
3. Confirm the expanded permanent gates actually pass at 100% and record their exact totals.
4. Re-list every inline thread and top-level bot comment; apply valid findings, explicitly decline
   false positives/noise, and resolve only after a documented disposition.
5. Rewrite PR #200 body into the canonical final audit record with exact-head coverage/check results.
6. Add final readiness comments to #200 and #189.
7. If an automated reviewer leaves a stale `CHANGES_REQUESTED` state after its findings are fixed,
   dismiss only that stale review with explicit evidence, as done on #199.
8. Merge #200 using `expected_head_sha` protection.
9. Confirm the resulting `main` merge SHA, close #189 as completed, and update #185 progress.
10. Create the first #190 branch from the exact #200 merge and begin durable persistence adapter
    coverage without waiting for user action.

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: active, #200 at finalization stage
- #190 — durable persistence adapters: queued next
- #191 — parser/provider/extraction adapters: queued
- #198 — product differentiation roadmap: active planning track

Issue #192 tracks native repository settings. Continue using short-lived disposable branches and
expected-head merge protection. Do not add redundant branch-cleanup automation while native settings
are the appropriate long-term solution.
