# Evaluation results

Issue #198 (Priority H) asks Tarkka to "publish results rather than only claiming reliability."
This document is where those results belong. It intentionally contains no fabricated numbers.

## 2026-09-13 — first published result

`tarkka eval` (see [`EVALUATION_CORPUS.md`](EVALUATION_CORPUS.md)) run against the actual downloaded
Project Gutenberg corpus bytes, staged and SHA-256-verified by the runner itself at
`.tarkka/real-world-corpus/`:

- **Commit:** `2a6aaf7`
- **OS:** Linux 6.8.0-138-generic x86_64
- **Python:** 3.12.13

```json
{
  "ok": true,
  "schema_version": 1,
  "total": 2,
  "complete": 2,
  "runs": [
    {
      "source_id": "gutenberg-frankenstein-epub",
      "staged_status": "ready",
      "stage": "complete",
      "artifact_id": "78a1e357-bb12-5472-8787-37759a8ad0a1",
      "document_id": "104a11d7-63ff-510d-889d-52590dd6faec",
      "error": null
    },
    {
      "source_id": "gutenberg-frankenstein-html",
      "staged_status": "ready",
      "stage": "complete",
      "artifact_id": "ca322903-74b0-5bb3-a028-83227d97563e",
      "document_id": "a9e789db-5ca3-5118-8191-6870deff5206",
      "error": null
    }
  ]
}
```

Both pinned sources verified against their recorded SHA-256, ingested through the real
`IngestService` with the expected parser (`epub`, `semantic_html`), built into a v3 proof bundle,
independently verified, and replayed to an exact content match. 2/2 complete, 0 errors.

## Reproducing a "nothing staged" run

Running the same command with nothing staged (the expected state in ordinary CI and a fresh
checkout) reports every recipe entry as expected-missing, not a benchmark result — this is the
report shape you'll see if you haven't downloaded the corpus yourself:

```json
{
  "ok": true,
  "schema_version": 1,
  "total": 2,
  "complete": 0,
  "runs": [
    {
      "source_id": "gutenberg-frankenstein-epub",
      "staged_status": "missing",
      "stage": "not_staged",
      "artifact_id": null,
      "document_id": null,
      "error": null
    },
    {
      "source_id": "gutenberg-frankenstein-html",
      "staged_status": "missing",
      "stage": "not_staged",
      "artifact_id": null,
      "document_id": null,
      "error": null
    }
  ]
}
```

Do not read a `missing`-only report as a benchmark pass or fail — it means the corpus was never
staged for that run, which is expected in ordinary CI and in a fresh checkout.

## How to produce a real result

1. Download the two sources listed in
   [`real_world_sources.json`](../tests/fixtures/evaluation/real_world_sources.json) yourself, and
   verify each against its pinned SHA-256 before staging it.
2. Place them at `.tarkka/real-world-corpus/frankenstein.epub` and
   `.tarkka/real-world-corpus/frankenstein.html` (or point `--staged-root` elsewhere).
3. Run `tarkka eval --staged-root .tarkka/real-world-corpus` and record the full JSON report,
   including the `tarkka` version/commit, OS, and Python version it ran under.
4. Append it as a new dated entry above, newest first, to track results over time and across
   environments/tarkka versions.

This corpus is deliberately tiny (two editions of one public-domain novel) and exercises only the
EPUB/semantic-HTML ingestion, proof-bundle, and replay paths — it is a reproducibility smoke test,
not a claim-extraction, retrieval, or verification-quality benchmark. `evaluate_retrieval` and the
staged-retrieval relevance set described in `EVALUATION_CORPUS.md` measure retrieval quality
separately and are not yet wired into `tarkka eval`; doing so is a follow-up (see the tracking issue
for this work) because it requires deciding how a `tarkka eval` run reproducibly builds a lexical
index, not just reusing what already exists.
