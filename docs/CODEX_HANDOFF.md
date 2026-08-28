# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/durable-persistence-coverage-ratchet`
**Active PR:** #201 — `test: ratchet PostgreSQL persistence foundation coverage`
**Active issue:** #190 — durable persistence adapter coverage
**Parent program:** #185 — historical branch coverage to 100%
**Product roadmap:** #198 — auditable/replayable research differentiation

> `AGENTS.md` is authoritative. GitHub issues, pull requests, review threads, workflow runs, and
> commits are the historical audit trail. Always re-read the live PR head because this handoff update
> advances it.

## Current objective

Finish and merge PR #201 as the first small #190 persistence slice. The PostgreSQL connection,
migration, and acquisition-provenance foundation has reached 100% statement + branch coverage on the
latest validated source head. A permanent CI ratchet has been added; validate the new exact head,
review every bot comment, finalize the PR record, and merge with expected-head protection. Then start
the next coherent #190 repository slice from the exact merge SHA rather than growing #201 further.

No user action is required for routine PR merging.

## Completed program baseline

- #187 — interface/runtime: completed / merged / permanently ratcheted.
- #188 — core domain invariants: completed / merged / permanently ratcheted.
- #189 — security/network acquisition: completed and closed.
- PR #200 merged as `bec2c3a2f7ab105ce50aac2157a243d9a375ab22`.

Permanent #189 protections now include:

- security/robots domain: **641 statements + 234 branches = 100%**;
- security application: **735 statements + 238 branches = 100%**;
- full-text/HTTP boundary: **363 statements + 136 branches = 100%**.

The final #200 validated source state had **1,545 passed / 36 deselected** and cumulative Phase-5
changed executable coverage **657/657 = 100%**.

## #201 selected persistence foundation

PR #201 deliberately starts #190 with a small PostgreSQL foundation rather than mixing in the larger
repositories:

- `src/tarkka/infrastructure/postgres/connection.py` — baseline 88%;
- `src/tarkka/infrastructure/postgres/migrations.py` — baseline 93%;
- `src/tarkka/infrastructure/postgres/acquisition_recorder.py` — baseline 93%.

These modules define optional dependency behavior, retry/error taxonomy, migration durability/locking,
and append-only acquisition provenance used by the larger persistence adapters.

## Latest fully validated #201 source result

Latest fully validated source head before the CI-ratchet/handoff commits:
`0c99d0d76fc0c38183ab39a512e5958ce1c1f507`.

Exact Python 3.13 result:

- **1,562 passed / 36 deselected**;
- repository aggregate: **12,273 statements / 680 misses; 3,854 branches / 504 partials = 92%**;
- `postgres/acquisition_recorder.py`: **44 statements + 10 branches = 100%**;
- `postgres/connection.py`: **42 statements + 8 branches = 100%**;
- `postgres/migrations.py`: **82 statements + 22 branches = 100%**;
- selected PostgreSQL persistence foundation: **168 statements + 40 branches = 100%**;
- cumulative Phase-5 executable changed lines: **657/657 = 100%**;
- PR changed executable source lines at this test-only source head: **0/0 = 100%**.

That exact head passed Python 3.11, Python 3.12, Python 3.13, Ruff, strict mypy, SQLFluff, zizmor,
Dependency Review, and the dedicated `PostgreSQL repositories` contract workflow. PR Agent was still
finishing at the last source-head snapshot.

Commit `bcdd26bc1ff31cfcd3798c463227c1af07e67c5e` adds the permanent
`Enforce PostgreSQL persistence foundation coverage` CI gate for all three modules. This handoff
commit is newer still, so revalidate the exact live head before merge.

## #201 behavior and failure contracts

### PostgreSQL connection boundary

`tests/test_postgres_connection_hardening.py` now covers:

- trimmed `TARKKA_DATABASE_URL` settings loading;
- clear optional-dependency failure when psycopg is unavailable;
- exact DSN pass-through on successful connection;
- transient `OperationalError` / `InterfaceError` translation;
- permanent driver-error translation;
- preservation of original exceptions as causes;
- translation behavior when psycopg itself is unavailable;
- unrelated application exceptions remaining untranslated;
- malformed driver error-class attributes not being mistaken for retryable errors.

### Migration durability / locking

`tests/test_postgres_migrations.py` now covers:

- numeric ordering, immutable checksums, invalid names, duplicate versions, and empty catalogs;
- both packaged-wheel migration discovery and editable-source fallback;
- append-only application and checksum recording;
- exact matching-history skips;
- changed/unknown history rejection;
- advisory-lock failure translation;
- connection cleanup when lock acquisition fails;
- no advisory unlock attempt when the lock was never acquired.

The first CI oracle showed the packaged-wheel `return bundled` path as the sole remaining line; a
focused packaged-directory test closed that real packaging branch instead of using an exclusion.

### Acquisition provenance recording

`tests/test_postgres_acquisition_recorder_unit.py` now covers:

- mapping and JSON-string metadata round-trip;
- rejection of non-object decoded metadata;
- append-only insert behavior;
- exact-retry idempotency;
- conflicting retry rejection;
- missing-artifact rejection;
- translated driver failure with original cause;
- untranslated application failure preservation;
- connection cleanup on both failure classes.

## Permanent CI ratchet

`Enforce PostgreSQL persistence foundation coverage` now includes:

- `src/tarkka/infrastructure/postgres/acquisition_recorder.py`;
- `src/tarkka/infrastructure/postgres/connection.py`;
- `src/tarkka/infrastructure/postgres/migrations.py`.

Expected validated total after the CI-ratchet commit: **168 statements + 40 branches = 100%**.
Do not merge until the exact live head confirms this step passes.

## Review state

At the initial #201 review sweep there were no inline review threads. Continue the `AGENTS.md` review
contract after the CI-ratchet and handoff commits: read every new inline thread, review submission,
and top-level bot comment; apply valid findings, explicitly reply to substantive comments, document
well-founded declines, and resolve only after the disposition is complete.

Do not dismiss generic or stale review state until the underlying finding has been checked against the
latest code. Qodo may remain paused due subscription status; informational rate-limit/billing messages
are noise rather than code findings.

## Exact next actions

1. Read live PR #201 head SHA after this handoff commit.
2. Confirm CI, Python 3.11/3.12/3.13, Quality, Dependency Review, PR Agent, and dedicated PostgreSQL
   repository contracts on that exact head.
3. In Python 3.13 logs, confirm `Enforce PostgreSQL persistence foundation coverage` passes at
   **168 statements + 40 branches = 100%**.
4. Re-list every inline review thread, review submission, and top-level bot comment; disposition all
   substantive feedback.
5. Mark #201 ready for review, rewrite the PR body into the canonical final audit record, and add a
   final readiness/progress comment.
6. If a stale automated `CHANGES_REQUESTED` review alone blocks merge after its findings are fully
   resolved, dismiss only that stale review with explicit evidence.
7. Merge #201 using `expected_head_sha` protection and record the resulting `main` SHA on #190/#185.
8. Start the next small #190 branch from that exact merge SHA.

## Next #190 candidate slices

Prefer frequent mergeable slices. Good next candidates from the latest coverage oracle are:

- high-coverage PostgreSQL repository contracts: `citation_context_repository.py` (96%),
  `work_repository.py` (93%), and `verification_repository.py` (90%);
- then lower-coverage PostgreSQL repositories: research (85%), source observation (80%), extraction
  (78%);
- JSON persistence can follow in coherent parity/atomic-write groups;
- `storage/locking.py` remains a distinct failure-injection target and should not be casually bundled
  into a repository PR merely to raise aggregate coverage.

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: completed / closed
- #190 — durable persistence adapters: active via #201
- #191 — parser/provider/extraction adapters: queued
- #198 — product differentiation roadmap: active planning track

Issue #192 tracks native repository settings. Continue using short-lived disposable branches and
expected-head merge protection. Do not add redundant branch-cleanup automation while native settings
are the appropriate long-term solution.
