# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/postgres-repository-contract-coverage`
**Active PR:** #202 — `test: ratchet PostgreSQL repository contract coverage`
**Active issue:** #190 — durable persistence adapter coverage
**Parent program:** #185 — historical branch coverage to 100%
**Product roadmap:** #198 — auditable/replayable research differentiation

> `AGENTS.md` is authoritative. GitHub issues, pull requests, review threads, workflow runs, and
> commits are the historical audit trail. Always re-read the live PR head because this handoff update
> advances it.

## Current objective

Finish and merge PR #202 as the second small #190 persistence slice. The selected citation-context,
Work, and verification PostgreSQL repositories reached 100% statement + branch coverage on exact
source head `aa26b7268370a2237f21d274d3f974baae8ba8f1`. A permanent CI ratchet has now been added; validate
the new exact head, complete the full bot-review sweep, finalize the PR record, and merge with
`expected_head_sha` protection. Then start the next lower-coverage PostgreSQL repository slice from
the exact resulting `main` SHA.

No user action is required for routine PR merging.

## Completed program baseline

- #187 — interface/runtime: completed / merged / permanently ratcheted.
- #188 — core domain invariants: completed / merged / permanently ratcheted.
- #189 — security/network acquisition: completed / closed / permanently ratcheted.
- #201 — first #190 PostgreSQL persistence foundation slice: merged as
  `e930b83443b582e7dd5284df9d674e584f255375`.

Permanent #201 PostgreSQL foundation gate:

- `postgres/acquisition_recorder.py`: **44 statements + 10 branches = 100%**;
- `postgres/connection.py`: **42 + 8 = 100%**;
- `postgres/migrations.py`: **82 + 22 = 100%**;
- combined: **168 statements + 40 branches = 100%**.

Exact #201 pre-merge validation: **1,562 passed / 36 deselected**, Python 3.11/3.12/3.13 + Quality
green, dedicated PostgreSQL repository contracts green, Dependency Review + PR Agent green, and
cumulative Phase-5 executable changed lines **657/657 = 100%**.

## #202 selected repository-contract slice

PR #202 deliberately stays limited to three high-coverage repositories that share idempotency,
row-decoding, error-translation, and connection/transaction cleanup contracts:

- `src/tarkka/infrastructure/postgres/citation_context_repository.py` — baseline 96%;
- `src/tarkka/infrastructure/postgres/work_repository.py` — baseline 93%;
- `src/tarkka/infrastructure/postgres/verification_repository.py` — baseline 90%.

The focused hardening lives in `tests/test_postgres_repository_coverage_hardening.py` rather than
rebuilding the larger existing unit/contract suites.

## Latest fully validated #202 source result

Exact validated source head before CI-ratchet/handoff commits:
`aa26b7268370a2237f21d274d3f974baae8ba8f1`.

Python 3.13 result:

- **1,570 passed / 36 deselected**;
- repository aggregate: **12,273 statements / 669 misses; 3,854 branches / 495 partials = 92%**;
- `postgres/citation_context_repository.py`: **156 statements + 28 branches = 100%**;
- `postgres/work_repository.py`: **115 statements + 22 branches = 100%**;
- `postgres/verification_repository.py`: **58 statements + 10 branches = 100%**;
- selected repository-contract slice: **329 statements + 60 branches = 100%**;
- cumulative Phase-5 executable changed lines: **657/657 = 100%**;
- current source diff is test-only: **0/0 changed executable production lines = 100%**.

The same exact head passed Python 3.11, Python 3.12, Python 3.13, Ruff, strict mypy, SQLFluff,
zizmor, Dependency Review, and PR Agent.

Commit `c98d951e01f4374ab7ef91294560d0776261384e` adds the permanent
`Enforce PostgreSQL repository contract coverage` CI gate for all three modules. This handoff commit
is newer still, so revalidate the exact live head before merge.

## #202 behavior / failure contracts closed

### Citation context repository

- exact stable-record retry is idempotent;
- empty passage sets and zero limits short-circuit without SQL;
- `limit=None` emits an unbounded query with the expected offset parameters;
- connection failures route through the shared PostgreSQL error taxonomy and preserve the original
  cause.

### Work repository

- transaction-body application failures remain untranslated when they are not driver failures;
- context-local transaction connection state is reset on failure;
- active-transaction query failures are translated when appropriate and preserve the original cause;
- active-transaction query failures remain the original exception when translation returns `None`;
- connections close and transaction context does not leak after either failure class.

The first #202 oracle left only Work line 254 (the untranslated active-transaction query failure).
The final focused regression closed that real branch and also fixed Ruff SIM117 without changing
behavior.

### Verification repository

- successful relation insert path;
- missing-claim rejection after a non-insert;
- `get_relation()` found and missing paths;
- connection failure translation with original cause preservation.

## Permanent CI ratchets

Existing #190 foundation gate:

```bash
uv run --no-sync coverage report \
  --include=src/tarkka/infrastructure/postgres/acquisition_recorder.py,src/tarkka/infrastructure/postgres/connection.py,src/tarkka/infrastructure/postgres/migrations.py \
  --fail-under=100
```

New #202 repository-contract gate:

```bash
uv run --no-sync coverage report \
  --include=src/tarkka/infrastructure/postgres/citation_context_repository.py,src/tarkka/infrastructure/postgres/work_repository.py,src/tarkka/infrastructure/postgres/verification_repository.py \
  --fail-under=100
```

Expected #202 gate total: **329 statements + 60 branches = 100%**.

## Local Python 3.13 coverage reproduction

CodeRabbit's late #201 review correctly asked the handoff to document a local reproduction path for
the exact coverage evidence. From the repository root:

```bash
uv sync --frozen --group dev --extra mcp
uv run --no-sync pytest -m "not external" \
  --cov=tarkka --cov=scripts --cov-branch \
  --cov-report=term-missing --cov-report=xml
```

Then run either permanent gate command above against the generated coverage data.

If a gate fails, use the `term-missing` output (and `coverage.xml` when needed) to identify the exact
missing statements/branches, rerun the smallest relevant tests, and add behavior/failure coverage for
the reachable contract. Do **not** weaken `--fail-under`, add exclusions/`pragma: no cover`, or create
meaningless tests merely to move the percentage.

## Review-bot disposition

### Late #201 CodeRabbit review

- **Accepted:** add local Python 3.13 coverage generation + exact 3-file gate reproduction + debug
  guidance to the handoff. This snapshot implements that request; reply to and resolve merged #201
  thread `PRRT_kwDOT99L386dGNJ1` with this commit as evidence once the live commit SHA is known.
- **Declined:** generic 80% test-helper docstring metric. Tarkka does not use a test-docstring coverage
  target, and adding low-value docstrings to private fixtures/fakes would be score-padding rather than
  better behavioral coverage.

### #202

No substantive #202 bot finding has been accepted/declined yet on the post-ratchet head. Follow the
full `AGENTS.md` contract: after the ratchet/handoff commits, read every inline thread, review
submission, and top-level bot comment; explicitly disposition useful findings before merge.

## Exact next actions

1. Read live PR #202 head after this handoff commit.
2. Confirm CI, Python 3.11/3.12/3.13, Quality, Dependency Review, PR Agent, and the dedicated
   PostgreSQL repository workflow on that exact head.
3. Confirm `Enforce PostgreSQL repository contract coverage` passes at
   **329 statements + 60 branches = 100%**.
4. Reply to merged #201 CodeRabbit comment `3878850030` with the handoff commit evidence and resolve
   thread `PRRT_kwDOT99L386dGNJ1`.
5. Mark #202 ready for review and perform the complete inline/top-level/review-submission sweep.
6. Apply valid feedback; document any well-founded decline; never dismiss a review before checking
   the underlying finding against current code.
7. Rewrite #202 body into the canonical final audit record and add final readiness/progress comments.
8. Merge #202 with exact `expected_head_sha` protection.
9. Record the resulting `main` SHA on #190 and #185.
10. Start the next small #190 branch from that exact merge SHA.

## Next #190 candidate slices

Prefer frequent mergeable slices. Current lower-coverage PostgreSQL candidates:

- `research_repository.py` — 85%;
- `source_observation_repository.py` — 80%;
- `extraction_repository.py` — 78%.

Choose one coherent repository or a tightly coupled pair based on shared contracts; do not bundle all
three merely to raise aggregate coverage. JSON persistence parity/atomic-write slices can follow.
`storage/locking.py` remains a distinct failure-injection target and should stay separate unless a
specific repository contract genuinely requires it.

## Program / repository hygiene

- #187 — interface/runtime: completed / merged
- #188 — core domain invariants: completed / merged
- #189 — security/network acquisition: completed / closed
- #190 — durable persistence adapters: active via #202
- #191 — parser/provider/extraction adapters: queued
- #198 — product differentiation roadmap: active planning track

Issue #192 tracks native repository settings. Continue using short-lived disposable branches and
expected-head merge protection.
