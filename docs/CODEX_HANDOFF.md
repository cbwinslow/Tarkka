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

Finish and merge PR #200 with expected-head protection after validating this final handoff-only head
and completing the last reviewer sweep. PR #200 completes the selected #189 security/network coverage
scope. After merge, close #189 and continue directly into #190 durable persistence adapters.

No user action is required for routine PR merging.

## Merged #189 work before #200

- PR #194 merged as `2c5f797272a3ac23be91c618bb524410be0bb653`.
- PR #195 merged as `8ef51a637dffbb01bf6b5c5c23bc3ee26346488f`.
- PR #196 merged as `9771cd4405248eae6df45978d8b1664e6a5d085c`.
- PR #197 merged as `7eca7c077e474b0b63580d10522d2393eaa88e4a`.
- PR #199 merged as `7ddd684d0127a17db85005d37fcc94c4f45b1385`.

Inherited permanent 100% gates before #200 included:

- security/robots domain: **641 statements + 234 branches = 100%**;
- security application after #199: **693 statements + 232 branches = 100%**;
- HTTP resolver/transport boundary after #197: **193 statements + 66 branches = 100%**;
- Phase 5 agent-serving, coverage tooling, interface/runtime, and #188 core-domain invariants.

## #200 latest fully validated result

Latest fully validated head before this handoff commit:
`7fc0429924e0be8708969e548b2142fd2de1eea5`.

Exact Python 3.13 result:

- **1,545 passed / 36 deselected**;
- repository aggregate: **12,273 statements / 690 misses; 3,854 branches / 511 partials = 92%**;
- `application/full_text.py`: **42 statements + 6 branches = 100%**;
- `infrastructure/full_text/http.py`: **136 statements + 58 branches = 100%**;
- `ports/full_text.py`: **34 statements + 12 branches = 100%**;
- application + HTTP adapter pair: **178 statements + 64 branches = 100%**;
- complete full-text resource/application/HTTP contract: **212 statements + 76 branches = 100%**;
- expanded security application permanent gate: **735 statements + 238 branches = 100%**;
- expanded full-text/HTTP boundary permanent gate: **363 statements + 136 branches = 100%**;
- cumulative Phase 5 executable changed lines: **657/657 = 100%**;
- current PR changed executable source lines: **1/1 = 100%**.

The same exact head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, zizmor, Package,
Dependency Review, and PR Agent.

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

`tests/test_full_text_resource_security.py` was added in direct response to reviewer feedback and
explicitly protects the invariant relied upon by the application simplification:

- blank provider/source/media-type/filename rejection;
- POSIX traversal and absolute path rejection;
- Windows traversal and absolute path rejection;
- NUL-byte filename rejection;
- valid single-component filename acceptance;
- immutable copied metadata.

## Production simplification justified by invariant

`FullTextResource.__post_init__` and `_is_safe_filename()` are the authoritative filename safety
contract. They reject blank filenames, `.`/`..`, NUL bytes, POSIX traversal/absolute paths, and Windows
traversal/absolute paths by requiring both `PurePosixPath(filename).name == filename` and
`PureWindowsPath(filename).name == filename`.

The acquisition orchestrator's second `path.parent != root` escape check was therefore unreachable
through a valid `FullTextResource`. It was removed rather than reached by constructing invalid frozen
objects. Reviewer feedback correctly noted that this architectural dependency needed explicit tests;
`ports/full_text.py` is now itself at 100% statement + branch coverage and permanently ratcheted.

## Permanent CI ratchets added by #200

`Enforce security application coverage` now includes `src/tarkka/application/full_text.py`, producing
**735 statements + 238 branches = 100%**.

`Enforce HTTP transport coverage` now protects:

- `src/tarkka/ports/full_text.py`;
- `src/tarkka/ports/http_transport.py`;
- `src/tarkka/infrastructure/full_text/http.py`;
- `src/tarkka/infrastructure/web/pinned_http_transport.py`.

That gate is **363 statements + 136 branches = 100%**.

## Review-bot disposition

- Codex inline finding requesting permanent full-text coverage gates was valid, already applied on
  later commits, explicitly replied to, and resolved.
- The PR Reviewer Guide's path-traversal concern was valid as a test-visibility concern. The production
  invariant was verified in `FullTextResource`, and explicit security tests were added rather than
  merely dismissing the warning.
- The same reviewer guide's earlier ticket-compliance warnings about missing coverage results, CI
  ratchets, and handoff updates are now stale: all three are present and validated on `7fc0429...`.
- Qodo is paused because its subscription is inactive.
- CodeRabbit was rate-limited and did not emit an actionable code finding at the last sweep.

Re-run the live reviewer sweep after this final documentation commit and disposition any newly emitted
substantive feedback before merging.

## Exact next actions

1. Read live PR #200 head SHA after this handoff commit.
2. Confirm Python 3.11/3.12/3.13, Quality, Package, Dependency Review, and PR Agent on that exact head.
3. Re-list every inline review thread, review submission, and top-level bot comment; apply valid new
   findings and explicitly document declines/noise.
4. Rewrite PR #200 body into the canonical final audit record using exact-head validation results.
5. Add final readiness comments to #200 and #189 and a progress update to #185.
6. If an automated reviewer leaves a stale `CHANGES_REQUESTED` state after all findings are fixed,
   dismiss only that stale review with explicit evidence.
7. Merge #200 using `expected_head_sha` protection and confirm the resulting `main` merge SHA.
8. Close #189 as completed and record its permanent-gate totals.
9. Create the first #190 branch from the exact #200 merge and begin durable persistence adapter
   coverage without waiting for user action.

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: active only until #200 merges
- #190 — durable persistence adapters: queued next
- #191 — parser/provider/extraction adapters: queued
- #198 — product differentiation roadmap: active planning track

Issue #192 tracks native repository settings. Continue using short-lived disposable branches and
expected-head merge protection. Do not add redundant branch-cleanup automation while native settings
are the appropriate long-term solution.
