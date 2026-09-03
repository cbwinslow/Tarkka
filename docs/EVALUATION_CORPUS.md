# Real-world evaluation corpus

The deterministic suite uses small local fixtures. The real-world corpus complements those tests
with a source recipe, not redistributed third-party files. Its first version is
[`tests/fixtures/evaluation/real_world_sources.json`](../tests/fixtures/evaluation/real_world_sources.json).

Each entry pins a canonical URL, acquired SHA-256, rights note, media type, expected parser, and
whether that parser is currently optional. Downloaded files belong in an ignored local directory
such as `.tarkka/real-world-corpus`; ordinary CI must not fetch them.

The initial recipe covers public-domain EPUB and HTML plus a PDF whose result is explicitly
conditional on the optional Docling adapter. A future isolated runner will verify the retained
artifact hash, ingestion outcome, normalized structure, claim/evidence lineage, proof bundle, and
replay against this recipe. It must report unsupported optional capabilities as expected outcomes,
not successes or silent omissions.

Expand the recipe only with sources whose rights/access posture is recorded. Keep provider snapshots
and live smoke checks separate from deterministic fixture tests.
