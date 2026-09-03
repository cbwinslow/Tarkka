# Real-world evaluation corpus

The deterministic suite uses small local fixtures. The real-world corpus complements those tests
with a source recipe, not redistributed third-party files. Its first version is
[`tests/fixtures/evaluation/real_world_sources.json`](../tests/fixtures/evaluation/real_world_sources.json).

Each entry pins a canonical URL, acquired SHA-256, rights note, media type, expected parser, and
whether that parser is currently optional. Downloaded files belong in an ignored local directory
such as `.tarkka/real-world-corpus`; ordinary CI must not fetch them.

The initial recipe covers public-domain EPUB and HTML. PDF coverage will be added only after a
source has a recorded rights/access decision and a repeatable optional-parser expectation. A future
isolated runner will verify the retained artifact hash, ingestion outcome, normalized structure,
claim/evidence lineage, proof bundle, and replay against this recipe. It must report unsupported
optional capabilities as expected outcomes, not successes or silent omissions.

## How to run

Synchronize the development environment, then validate the recipe without downloading anything:

```bash
uv sync --group dev
uv run pytest tests/test_real_world_corpus_manifest.py
```

The staged-artifact runner is not implemented yet. Do not treat this manifest check as an ingestion
benchmark or invoke network fetches from ordinary CI.

## How to debug

If a hash changes, retain the previous recipe entry and investigate the fetched bytes, canonical URL,
and rights status before updating any expectation. If a parser or capability expectation fails, first
confirm the locally installed adapter/version and preserve the failure as an explicit expected result
when the adapter is optional. The future runner will add artifact, structural, proof-bundle, and
replay diagnostics; until then, use the existing local `tarkka ingest`, `bundle verify`, and `replay`
commands against a manually staged ignored file.

Expand the recipe only with sources whose rights/access posture is recorded. Keep provider snapshots
and live smoke checks separate from deterministic fixture tests.
