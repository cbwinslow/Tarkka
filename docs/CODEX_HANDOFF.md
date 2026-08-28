# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC
**Repository:** `cbwinslow/Tarkka`
**Default branch:** `main`
**Active branch:** `test/security-network-coverage-ratchet`
**Active PR:** #194 — `test: ratchet security and network coverage to 100%`
**Active issue:** #189 — security/network acquisition coverage
**Parent program:** #185 — historical branch coverage to 100%

> `AGENTS.md` is authoritative. This file is the current execution baton, not a journal. GitHub issues,
> pull requests, reviews, workflow runs, and commits are the historical audit trail. Always verify the
> live PR head because the commit updating this file necessarily advances the branch.

---

## 1. Current objective

Merge the first #189 security-domain slice in PR #194 after one final documentation-inclusive workflow
and review sweep. Then continue #189 from the resulting `main` with a fresh robots/crawl PR rather than
growing #194.

No user action is currently required.

---

## 2. Merged baseline

PR #193 / issue #188 completed the core-domain slice and merged into `main` as:

`326c0d70f67b3cea38144e45696641fd663625bf`

Permanent inherited gates before #194:

- Phase 5 agent-serving/context-package/telemetry: **549 statements + 122 branches = 100%**;
- coverage checker: **154 statements + 70 branches = 100%**;
- interface/runtime: **1,013 statements + 168 branches = 100%**;
- thirteen core-domain modules: **1,158 statements + 416 branches = 100%**;
- changed executable Python lines: **100% required**;
- cumulative Phase 5 executable range from immutable anchor
  `7e4f51ddb14a44c1b32a782d3cbdbb7c06a41b01`: **100% required**.

Repository deterministic coverage after #188 was 90% with 1,289 passed / 36 deselected.

---

## 3. #194 completed source result

Validated source/test head immediately before this handoff commit:

`8f3158f05be752c36692f31a8cd62c083dcd7f6a`

Python 3.13 result:

- **1,322 passed / 36 deselected**;
- repository aggregate: **12,287 statements / 874 misses; 3,868 branches / 656 partials = 90%**;
- `domain/http_observations.py`: **172 statements + 52 branches = 100%**;
- `domain/policy_fetch_finalization.py`: **34 + 12 = 100%**;
- `domain/resource_acquisition.py`: **128 + 44 = 100%**;
- first #189 security-domain ratchet: **334 statements + 108 branches = 100%**;
- cumulative Phase 5 executable changed lines: **635/635 = 100%**;
- current #194 executable changed lines: **18/18 = 100%**.

The same source head passed Python 3.11, Python 3.12, Ruff, strict mypy, SQLFluff, zizmor, and every
inherited 100% coverage gate. Package and Dependency Review were also green when this handoff was
written; re-check all workflows on the live handoff head before merge.

---

## 4. Security defects found and fixed in #194

Coverage-guided review found real durable-provenance sanitation weaknesses in nested URLs:

1. Scheme-relative nested URLs containing userinfo could preserve username/password values.
2. Malformed scheme-relative authorities could fall back to preserving nested sensitive query values.
3. Invalid IDNA hostnames or malformed ports needed a fail-closed path that did not re-persist the
   untrusted authority.

Current behavior:

- valid nested HTTP(S) URIs are normalized recursively;
- scheme-relative userinfo is dropped;
- malformed/un-normalizable nested authorities are dropped;
- path/query/fragment components are retained only after recursive sensitive-parameter sanitation;
- genuinely unparseable nested values are preserved only when the URI parser cannot safely recover
  components at all;
- generated property tests assert credential fields are structurally absent and sensitive query values
  are `[REDACTED]` without brittle whole-URI substring checks.

No live network access is required by these tests.

---

## 5. Review disposition

All review threads present before this snapshot were replied to and resolved.

Substantive reviewer findings improved the branch by:

- replacing brittle Hypothesis substring assertions with parsed userinfo/query assertions;
- handling invalid-IDNA nested hosts without leaking the authority or query secrets;
- strengthening malformed-port behavior from permissive preservation to fail-closed sanitized
  components.

A suggestion to widen `ResourceAcquisitionPolicy.allows_uri` from `str` to `str | None` was declined:
the production API remains a string contract, while the test-only `cast(str, None)` intentionally
exercises the defensive runtime guard without changing the public type.

Re-list review threads and submitted reviews on the final live head before merging because bots can add
new findings after this snapshot.

---

## 6. Exact next actions

1. Read the live #194 head SHA; this handoff commit is newer than `8f3158f...`.
2. Confirm every triggered workflow on that exact head is green, especially:
   - Python 3.11 / 3.12 / 3.13;
   - Ruff / strict mypy / SQLFluff / zizmor;
   - first #189 security-domain gate = 100%;
   - inherited Phase 5/interface/core-domain gates = 100%;
   - cumulative Phase 5 and current-PR changed-line coverage = 100%;
   - Package, Dependency Review, PR Agent, and any other triggered checks.
3. Re-list inline review threads and submitted reviews; disposition/resolve all meaningful findings.
4. Update PR #194 and issue #189 with final exact-head readiness.
5. Merge #194 into `main` using expected-head SHA protection.
6. Leave #189 open and create a fresh branch from the #194 merge commit for the robots/crawl domain
   batch.

---

## 7. Next #189 PR: robots/crawl domain batch

Latest measured debt:

- `domain/crawl_access.py`: **81%** — 73 statements, 30 branches;
- `domain/robots_cache.py`: **82%** — 53 statements, 24 branches;
- `domain/robots_rules.py`: **87%** — 183 statements, 70 branches;
- `application/robots_access.py`: already **100%**.

Recommended next merge boundary:

1. close validation/state edge branches in `crawl_access.py`;
2. close cache lifetime/UTF-8/provenance/time-comparison boundaries in `robots_cache.py`;
3. close parser/group/rule/crawl-delay/path-normalization branches in `robots_rules.py`;
4. add a permanent 100% robots-domain coverage gate;
5. merge that small PR before moving to `application/robots_refresh.py`,
   `application/crawl_eligibility.py`, and `application/recursive_crawl.py`.

After robots/crawl, continue #189 into `ports/http_transport.py`,
`infrastructure/web/pinned_http_transport.py`, then HTTP acquisition/policy-fetch application services.

---

## 8. Program / repository hygiene

Coverage program:

- #187 — interface/runtime: **completed / merged**
- #188 — core domain invariants: **completed / merged**
- #189 — security/network acquisition: **active**
- #190 — durable persistence adapters: queued
- #191 — parser/provider/extraction adapters: queued

Issue #192 tracks native GitHub repository automation/settings. A live re-check found:

- `delete_branch_on_merge=false`;
- `allow_auto_merge=false`;
- `allow_update_branch=false`.

The current connector does not expose repository-setting or branch-delete mutations, so do not create a
redundant cleanup workflow. Continue using short-lived, clearly disposable branches and track enabling
native automatic merged-branch deletion in #192.
