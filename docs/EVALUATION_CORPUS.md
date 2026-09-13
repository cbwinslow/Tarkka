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

The staged-artifact runner is an offline application composition: first classify staged bytes by
the recipe's pinned digest, then run only READY artifacts through injected existing ingestion,
proof, verification, and replay services. Its versioned report preserves each source recipe entry,
staging outcome, artifact/document handles, terminal pipeline stage, and bounded failure message.
MISSING and HASH_MISMATCH artifacts never invoke ingestion. Do not treat this runner as a benchmark
or invoke network fetches from ordinary CI.

Hybrid retrieval can be evaluated offline before any staged source is available: provide versioned
query IDs, explicit relevant RetrievalSegment handles, and the ordered candidate handles to
`tarkka.evaluation.evaluate_retrieval`. The report exposes per-query precision/recall at K and
reciprocal rank plus aggregate means. It never infers relevance from model or lexical scores, and
does not select a retrieval model or fetch corpus inputs.

## Staged retrieval relevance

[`staged_retrieval_relevance.json`](../tests/fixtures/retrieval/staged_retrieval_relevance.json)
is the small, reviewed relevance set for the first successfully staged corpus. It records query IDs,
query text, the corpus source ID, exact persisted Document and RetrievalSegment handles, and the
canonical section/passage character span behind every relevance judgment. The manifest is bound to
the corpus-recipe name and lexical derivation/configuration identifiers. Revalidate it against the
selected persisted projections before scoring; a missing handle or changed span fails closed rather
than treating a regenerated segment as equivalent.

The dependency-free lexical baseline can be measured over the selected exact segments with
`evaluate_lexical_projection`. Supply vector or hybrid rankings only when their existing adapters
are actually configured. Otherwise report those modalities as unavailable with a reason: unavailable
is neither a failed ranking nor evidence that a reranker is needed. The current two-query fixture is
only a reproducibility slice, not a basis for selecting a retrieval model or reranker.

## How to debug

If a hash changes, retain the previous recipe entry and investigate the fetched bytes, canonical URL,
and rights status before updating any expectation. If a parser or capability expectation fails, first
confirm the locally installed adapter/version and preserve the failure as an explicit expected result
when the adapter is optional. The future runner will add artifact, structural, proof-bundle, and
replay diagnostics; until then, use the existing local `tarkka ingest`, `bundle verify`, and `replay`
commands against a manually staged ignored file.

Expand the recipe only with sources whose rights/access posture is recorded. Keep provider snapshots
and live smoke checks separate from deterministic fixture tests.
