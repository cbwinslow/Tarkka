# Real-world evaluation corpus

The deterministic suite uses small local fixtures. The real-world corpus complements those tests
with a source recipe, not redistributed third-party files. The original two-representation smoke
recipe is [`tests/fixtures/evaluation/real_world_sources.json`](../tests/fixtures/evaluation/real_world_sources.json).
The multi-format reproducibility profile is
[`tests/fixtures/evaluation/multiformat_sources.json`](../tests/fixtures/evaluation/multiformat_sources.json).

Each entry pins a canonical URL, acquired SHA-256, rights note, media type, expected parser, and
whether that parser is currently optional. Schema-v2 profiles additionally pin minimum normalized
section and passage counts. Those are preservation floors, not a general parser-quality score:
they make a silent loss of most source structure a typed evaluation failure without claiming that
the remaining structure is complete or semantically correct. Downloaded files belong in an ignored
local directory such as `.tarkka/real-world-corpus`; ordinary CI must not fetch them.

The v2 profile covers plain text, EPUB, semantic HTML, JATS/XML, and standalone LaTeX with already
supported parsers. PDF coverage will be added only after a source has a recorded rights/access
decision and a repeatable optional-parser expectation. The isolated runner verifies retained
artifact hashes, parser selection, bounded normalized structure, proof bundles, and replay. It does
not yet measure claim/evidence quality; unsupported optional capabilities must be explicit expected
outcomes, never silent omissions.

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

### `tarkka eval`

`tarkka eval` wires the staged-artifact runner above to the real local ingest, proof-bundle,
verification, and replay services (not a test double) and prints a deterministic JSON report:

```bash
tarkka eval --recipe tests/fixtures/evaluation/multiformat_sources.json \
  --staged-root .tarkka/multiformat-corpus
```

It never fetches the network. A source recipe entry with no staged bytes at `--staged-root` is
reported with `staged_status: "missing"` and `stage: "not_staged"` — an expected outcome, not a
failure, and carries `error: null`. Each recipe entry's terminal `stage` is one of `not_staged`,
`ingest`, `proof`, `verify`, `replay`, or `complete`; a failed `ingest`/`proof`/`verify`/`replay`
stage carries a bounded (512-character) `error` string describing the failure. Schema-v2 profiles
can also report `stage: "preservation"` after a successful ingest when a normalized section or
passage floor is missed; Artifact and Document handles remain in that result for diagnosis. Exit status is `0`
only when every recipe entry reaches `complete`, so it composes with CI gating. See
[`EVALUATION_RESULTS.md`](EVALUATION_RESULTS.md) for what this reports in an environment with no
downloaded corpus, and for what publishing real measured results requires.

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

The first opt-in local embedding run used the locally retained Apache-2.0
`sentence-transformers/all-MiniLM-L6-v2` revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with 384-dimensional L2-normalized
vectors and the `sentence-transformers-5.7.0;normalize_embeddings=true` configuration.
Across 1,542 staged source-backed segments at K=2, lexical scored MRR/precision/recall
of 1.0/0.75/0.75, vector scored 0.5/0.5/0.5, and reciprocal-rank hybrid scored
1.0/0.75/0.75. This small slice does not establish a default embedding model and supplies
no measured benefit for reranking. The model remains an explicit local optional dependency;
ordinary CI neither installs it nor downloads model bytes.

## How to debug

If a hash changes, retain the previous recipe entry and investigate the fetched bytes, canonical URL,
and rights status before updating any expectation. If a parser, capability, or preservation expectation fails, first
confirm the locally installed adapter/version and preserve the failure as an explicit expected result
when the adapter is optional. The future runner will add artifact, structural, proof-bundle, and
replay diagnostics; until then, use the existing local `tarkka ingest`, `bundle verify`, and `replay`
commands against a manually staged ignored file.

Expand the recipe only with sources whose rights/access posture is recorded. Keep provider snapshots
and live smoke checks separate from deterministic fixture tests. Do not lower a structural floor to
accept a regression; add a source-version/adapter change explanation and a new profile entry when a
legitimate upstream source revision is intentionally adopted.
