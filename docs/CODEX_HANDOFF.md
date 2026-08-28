# AI Handoff — Tarkka

**Snapshot timestamp:** 2026-08-28 UTC  
**Repository:** `cbwinslow/Tarkka`  
**Default branch:** `main`  
**Active branch:** `test/interface-runtime-coverage-ratchet`  
**Active PR:** #186 — `test: ratchet interface runtime coverage to 100%`  
**Active issue:** #187 — interface/runtime coverage slice  
**Parent program:** #185 — historical branch coverage to 100%

> `AGENTS.md` is authoritative. Read it first, then this snapshot, then #187/#186.
> This file is a current baton, not a journal; GitHub issues, PRs, reviews, and commits are the audit
> trail. The documentation commit that updates this snapshot advances the branch beyond any source
> head quoted below, so always read the live PR head before acting.

---

## 1. Current objective

Finish the first #185 historical-coverage slice by raising the complete interface/runtime boundary to
100% branch coverage and permanently ratcheting it in CI.

Target modules:

- `src/tarkka/__main__.py`
- `src/tarkka/interfaces/cli.py`
- `src/tarkka/interfaces/main.py`

Rules:

- no coverage exclusions or score-padding assertions;
- default tests remain deterministic/network-free;
- preserve CLI/API behavior unless a test exposes a real defect or dead branch;
- every meaningful bot finding must be verified, replied to, and resolved;
- completed coherent modules are promoted immediately to permanent 100% CI gates.

---

## 2. What is merged on `main`

PR #184 merged as `a2e601118ca6b1ad3e756324a809d7300c959372`.

Its final validated source head was `815f83533756c57a9deb61fbe6ebd134edee6b6c`:

- Python 3.13: **1,032 passed / 36 deselected**;
- Phase 5 subsystem: **549 statements + 122 branches = 100%**;
- `scripts/check_diff_coverage.py`: **154 statements + 70 branches = 100%**;
- protected Phase 5 executable diff: **617/617 = 100%**;
- final #184 executable diff: **38/38 = 100%**.

Permanent #184 invariants now on `main`:

- every changed executable Python line under `src/tarkka/` and `scripts/` must be covered;
- cumulative Phase 5 changes from immutable anchor
  `7e4f51ddb14a44c1b32a782d3cbdbb7c06a41b01` remain 100% covered;
- Phase 5 agent-serving/context-package/telemetry modules remain 100% branch-covered;
- the diff-coverage checker itself remains 100% branch-covered;
- bot-review triage and cross-agent handoff rules are defined in `AGENTS.md`.

Important #184 reviewer decisions are recorded in its threads/body. Do not reopen them without new
evidence.

---

## 3. PR #186 clean-base rebuild

PR #186 was originally stacked on #184. After #184 merged, its branch was force-reset to the exact
merge commit and only the intended interface/runtime work was restored. Do **not** reintroduce the old
stacked ancestry.

Clean base:

- `main` @ `a2e601118ca6b1ad3e756324a809d7300c959372`.

Restored/added work:

- `tests/test_cli_runtime_boundaries.py` — entrypoints, backend selection, parsers/providers,
  manifests, handle parsing, provider policy/cursors, Work payloads;
- `tests/test_cli_command_boundaries.py` — deterministic success/error contracts for ingest,
  discovery, Work save/show/enrich/acquire, inspect, and read;
- `.github/workflows/ci.yml` — permanent 100% ratchet for completed package/legacy CLI modules;
- `tests/test_main_runtime_boundaries.py` — first `interfaces/main.py` batch covering all handle
  parsers, claim-extractor configuration, and DB-upgrade serialization/error translation;
- this handoff snapshot.

The package entrypoint test intentionally uses `importlib.import_module("tarkka.__main__")` rather than
anonymous `runpy` execution so coverage is attributed to the real module.

---

## 4. Latest measured coverage

Clean-base Python 3.13 run for source head `ebdb58288fd3dfa9a7242c9201d6839f9a757051`:

- **1,056 passed / 36 deselected**;
- repository aggregate: **12,277 statements / 1,170 misses; 3,870 branches / 834 partials = 87%**;
- `src/tarkka/__main__.py`: **100%**;
- `src/tarkka/interfaces/cli.py`: **278 statements, 46 branches, 0 misses/partials = 100%**;
- `src/tarkka/interfaces/main.py`: **80%**, 135 statements still missed, 29 partial branches;
- inherited Phase 5 subsystem gate: **100%**;
- inherited coverage-checker gate: **100%**;
- cumulative Phase 5 executable diff: **617/617 = 100%**.

The same run had one non-functional Quality failure: two test lines were 101 characters and Ruff
rejected them. They have been reformatted on a later head. Python 3.11/3.12 and 3.13 tests themselves
passed.

A permanent CI step now protects `src/tarkka/__main__.py` and `src/tarkka/interfaces/cli.py` at 100%
while work continues on `interfaces/main.py`.

---

## 5. Current `interfaces/main.py` plan

The current uncovered lines are grouped rather than attacked randomly.

### Batch A — runtime/configuration boundaries

In progress / committed:

- all UUID/handle parser error branches;
- rule/model claim-extractor configuration;
- missing model endpoint/name configuration;
- optional provider/API-key/model-version propagation;
- DB-upgrade success payload and configuration failure.

### Batch B — identity/extraction contracts

Next:

- identity suggestion error + payload serialization;
- identity decision success/error translation;
- extract-claims model metadata branch and extraction failures;
- evidence payload variants;
- claims list/show error boundaries.

### Batch C — citation/verification/research-package boundaries

Then target only coverage-reported missing branches in citation pagination/repository absence,
verification errors/payloads, and research-package resource-link paths. Reuse existing CLI tests before
adding cases.

### Batch D — parser/dispatch tail

Finally cover remaining parser construction/delegation and module dispatch/entrypoint lines. If any
branch is unreachable, simplify production code instead of excluding it.

When `interfaces/main.py` reaches 100%, extend the permanent interface/runtime CI gate to include it.

---

## 6. Review / CI status

A PR reviewer-guide comment on the earlier clean-base head correctly noted two process gaps:

1. no permanent interface/runtime CI ratchet;
2. stale/missing handoff snapshot.

Both are now addressed by later commits. The guide was generated before those commits and must be
re-evaluated against the live head rather than treated as current truth.

At the last inline-thread sweep, #186 had **zero review threads**. Re-sweep after every meaningful push;
new reviewer comments may appear after this snapshot.

Current branch head immediately before this documentation update was
`cd9c47cb4bfb5100c420faa966ebb82c406b5e75`; read the live PR head because this documentation commit
advances it.

---

## 7. Exact next actions

1. Read the live #186 head SHA.
2. Inspect the newest CI run for Ruff, strict mypy, SQLFluff/zizmor, Python 3.11/3.12/3.13, the new
   completed-CLI ratchet, inherited Phase 5/checker gates, and changed-line coverage.
3. Inspect all top-level and inline bot comments added after this snapshot.
4. Apply/reply/resolve findings according to `AGENTS.md`.
5. Read the new Python 3.13 `interfaces/main.py` coverage after Batch A.
6. Implement Batch B using behavior-focused tests and existing test helpers where possible.
7. Repeat CI/review/coverage measurement after each meaningful batch.
8. Once `interfaces/main.py` is 100% branch-covered, add it to the permanent interface/runtime
   `--fail-under=100` CI gate.
9. Update #187, parent #185, PR #186 body/comments, and this snapshot with exact final metrics.
10. Mark #186 ready, perform the final-head reviewer sweep, and merge it to `main` only when all branch
    rules and required workflows pass.

---

## 8. Broader roadmap / GitHub automation

Coverage program child issues:

- #187 — interface/runtime (**active**)
- #188 — core domain invariants
- #189 — security/network acquisition
- #190 — durable persistence adapters
- #191 — parser/provider/extraction adapters

Repository automation issue #192 tracks GitHub-native settings that should not be duplicated as YAML:
CodeQL default setup/security-feature verification, delete-merged-branches, auto-merge, and
update-branch support. Do not add a duplicate CodeQL workflow or another generic AI reviewer.

Release/PyPI/SBOM/provenance automation should wait until the release policy is explicitly finalized.
