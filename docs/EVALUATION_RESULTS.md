# Evaluation results

Issue #198 (Priority H) asks Tarkka to "publish results rather than only claiming reliability."
This document is where those results belong. It intentionally contains no fabricated numbers.

## Current status: no published results yet

`tarkka eval` (see [`EVALUATION_CORPUS.md`](EVALUATION_CORPUS.md)) exists and runs the real local
ingest, proof-bundle, verification, and replay pipeline against the pinned corpus recipe. It has
not yet been run against the actual downloaded Project Gutenberg corpus bytes anywhere this
repository controls, so there are no measured pass/fail numbers to publish. Running it with nothing
staged reports every recipe entry as expected-missing, not a benchmark result:

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
4. Replace the placeholder result above with that real report, or append it as a dated entry below
   if you want to track results over time.

This corpus is deliberately tiny (two editions of one public-domain novel) and exercises only the
EPUB/semantic-HTML ingestion, proof-bundle, and replay paths — it is a reproducibility smoke test,
not a claim-extraction, retrieval, or verification-quality benchmark. `evaluate_retrieval` and the
staged-retrieval relevance set described in `EVALUATION_CORPUS.md` measure retrieval quality
separately and are not yet wired into `tarkka eval`; doing so is a follow-up (see the tracking issue
for this work) because it requires deciding how a `tarkka eval` run reproducibly builds a lexical
index, not just reusing what already exists.
