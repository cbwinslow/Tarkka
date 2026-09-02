# Similarity, Consensus, and Graph Projections

## Purpose

Tarkka should help users explore related material—such as all evidence about Allied forces in World
War I, inflation across countries and periods, or a historical figure—without pretending that
similar wording proves identity, agreement, or truth.

## Relationship graph projection

The canonical relational model already contains typed links among Artifacts, Documents, components,
Works, citations, resource links, Claims, Evidence, datasets, people, organizations, and future
concept/entity observations. Application services may expose bounded graph projections over those
relations for navigation, comparison, and agent retrieval.

Each edge must have a type, direction, provenance/basis, version, and confidence/review state where
applicable. Graph views must honor rights/access rules and explicit depth, count, byte, and token
budgets. A graph database is not a prerequisite: PostgreSQL remains the system of record until
measured queries justify another store.

## Similarity is a candidate, not a merge

Similarity may be lexical, structural, numeric, entity-aware, semantic, or domain-specific. The
pipeline is deliberately staged:

1. exact identifiers, normalized units/dates, and deterministic text keys;
2. fast fuzzy/lexical candidate generation;
3. embedding-based semantic candidate generation;
4. optional cross-encoder/domain reranking of a bounded candidate set;
5. persisted `SimilarityCandidate`/`ConsensusObservation` with scores, method/model/version,
   thresholds, inputs, and explanation summary;
6. explicit human or policy decision before any canonical equivalence, duplicate, support, or
   contradiction relation is created.

Semantic similarity never silently merges Claims, Works, entities, or facts. A candidate relation
must remain reversible and independently attributable to its source components.

## Consensus and fact quality

Do not manufacture a universal truth score. Keep observable quality dimensions separate:

- source authority, publication/revision state, and rights/access provenance;
- conversion/OCR quality;
- extraction/normalization confidence and version;
- evidence relation (`supports`, `contradicts`, `qualifies`, `uncertain`, etc.);
- independence/correlation of supporting sources;
- temporal, geographic, population, unit, and methodology scope;
- human-review state and quality-policy version.

A consensus observation may summarize agreement or disagreement only within an explicit scope. For
example, an inflation value must identify country/geography, period, frequency, measure/base,
revision, methodology, and source—not merely a number labelled “inflation.”

## Reusable implementation strategy

Use replaceable, versioned adapters: deterministic normalization/identifier checks first; a mature
fuzzy matcher for lexical candidates; embedding generation stored in pgvector; and a bounded reranker
only when it improves measured precision. Keep model downloads, licensing, data egress, and compute
cost explicit. Domain packs may supply entity resolution, ontologies, units, temporal policies, and
quality criteria without changing core identity/provenance rules.

## Required tests

- exact matches, near matches, and semantically related-but-distinct statements remain distinct;
- candidate generation/reranking is deterministic for a pinned model/version fixture;
- a decision records provenance and can be reversed without rewriting source history;
- graph traversal is bounded and preserves edge/source metadata;
- consensus output retains disagreement, uncertainty, scope, and source independence rather than
  flattening them into a single score.
