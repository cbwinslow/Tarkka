# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/security-http-acquisition-coverage`
**Active PR:** #199 — `test: harden HTTP acquisition and policy-fetch coverage`
**Active issue:** #189 — security/network acquisition coverage
**Parent program:** #185 — historical branch coverage to 100%
**Product roadmap:** #198 — auditable/replayable research differentiation

> `AGENTS.md` is authoritative. GitHub issues, pull requests, review threads, workflow runs, and
> commits are the historical audit trail. Always re-read the live PR head because this handoff update
> advances it.

## Current objective

Finish and merge PR #199 using expected-head protection after the documentation-inclusive exact-head
CI/review sweep. Then evaluate whether #189 is complete or has one final coherent security/network
slice before moving the historical coverage program to #190 durable persistence adapters.

No user action is required for routine PR merging.

## Merged #189 baseline

- PR #194 merged as `2c5f797272a3ac23be91c618bb524410be0bb653`.
- PR #195 merged as `8ef51a637dffbb01bf6b5c5c23bc3ee26346488f`.
- PR #196 merged as `9771cd4405248eae6df45978d8b1664e6a5d085c`.
- PR #197 merged as `7eca7c077e474b0b63580d10522d2393eaa88e4a`.
- Security/robots domain gate: **641 statements + 234 branches = 100%**.
- Crawl application gate before #199: **305 statements + 120 branches = 100%**.
- HTTP transport/resolver gate: **193 statements + 66 branches = 100%**.

Inherited permanent 100% gates also protect Phase 5 agent-serving, coverage tooling,
interface/runtime, and the completed #188 core-domain invariant set.

## #199 latest fully validated source result

Latest fully validated head before the CI-ratchet/handoff commits:
`c5e9d5ce491673dba2b7211cc9e3821857fd22dc`.

Python 3.13 result:

- **1,487 passed / 36 deselected**;
- repository aggregate: **12,276 statements / 720 misses; 3,856 branches / 534 partials = 92%**;
- `application/http_acquisition.py`: **248 statements + 82 branches = 100%**;
- `application/http_policy_fetch.py`: **140 statements + 30 branches = 100%**;
- completed acquisition/policy-fetch pair: **388 statements + 112 branches = 100%**;
- cumulative Phase 5 executable changed lines: **656/656 = 100%**;
- current PR changed executable source lines on that head: **4/4 = 100%**.

The same head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, zizmor, Package,
Dependency Review, and PR Agent.

Commit `04279960055d14f4df6717f449b0f9a42b8941d3` extends the permanent
`Enforce security application coverage` gate to include `http_acquisition.py` and
`http_policy_fetch.py`. This handoff commit is newer still, so revalidate the exact live head before
merging.

## #199 behavior and test hardening

The coverage pass added deterministic, network-free regression coverage for:

- request URI/durable-target and policy validation before network I/O;
- resolver and transport exception translation with durable failed checkpoints;
- exact hostname, resolved-address, byte-cap, and elapsed-time timeout propagation;
- independent DNS resolution and pinned-address routing across an absolute cross-host redirect;
- response overflow and already-exhausted byte budgets;
- redirect `Location` cardinality, whitespace, control-character, authority, and scheme validation;
- redirect pacing plus post-sleep elapsed-budget enforcement;
- invalid/backwards clocks and unbounded elapsed policies;
- finalization recovery, concurrent durable-state changes, missing outputs, retry-state persistence
  failure, wrong observation/artifact lineage, and completion-write interruption;
- artifact-store identity violations and policy-fetch journal/recovery failures.

The tests intentionally use injected resolver/transport/repository/clock boundaries and perform no
live network access.

## Production simplifications justified by invariants

Coverage analysis removed duplicate impossible-state checks rather than manufacturing invalid domain
objects to reach them:

- `PolicyFetchFinalization.__post_init__` recomputes the artifact-derived observation and rejects an
  inconsistent `observation_id`, so `_recover_policy_result()` does not duplicate that identity check.
- `TraversalTarget.__post_init__` requires both finalization identifiers for every `FINALIZING`
  target, so recovery safely narrows those fields after checking the durable status.
- `ResourceAcquisitionPolicy.allows_uri()` rejects missing hostnames before `_request_once()` reaches
  its normalized hostname cast, so a second hostname-`None` check was unreachable.

These decisions were explicitly re-verified after the persistent reviewer guide raised them as
possible regressions.

## Review-bot disposition

All inline review threads observed through head `c5e9d5c` were addressed/resolved. Useful feedback was
applied, including:

- hostname-aware resolver assertions and an explicit cross-host redirect regression;
- transport argument capture for security/budget contracts;
- deterministic resolver/transport exception injection;
- post-sleep elapsed-budget validation;
- typed test factories without broad `arg-type` suppressions;
- finalization-abandonment and redirect-validation edge cases;
- deterministic zero-clock injection for direct helper tests.

Qodo remains paused because its subscription is inactive. CodeRabbit's generic test-docstring
coverage warning is not a Tarkka repository policy and should not be satisfied with low-value test
helper docstrings. Re-run the live review sweep after the final documentation/CI commits and disposition
any new substantive findings before merge.

## Exact next actions

1. Read live PR #199 head SHA (newer than `0427996` because of this handoff commit).
2. Confirm Python 3.11/3.12/3.13, Quality, Package, Dependency Review, and PR Agent are green on that
   exact head.
3. Confirm the expanded `Enforce security application coverage` step passes at 100% and therefore
   permanently protects the acquisition/policy-fetch pair.
4. Re-list all inline review threads and top-level bot feedback; reply/resolve every substantive new
   finding.
5. Refresh PR #199 body with final coverage/check results and the invariant-based review decisions.
6. Add a final #199/#189 progress comment and merge #199 with `expected_head_sha` protection.
7. Read `main` after merge, update #189 status, and continue directly into the next coherent coverage
   slice without waiting for user action.

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: active, #199 at finalization stage
- #190 — durable persistence adapters: queued
- #191 — parser/provider/extraction adapters: queued
- #198 — product differentiation roadmap: active planning track

Issue #192 tracks native repository settings. Continue using short-lived disposable branches and
expected-head merge protection. Do not add redundant branch-cleanup automation while native settings
are the appropriate long-term solution.
