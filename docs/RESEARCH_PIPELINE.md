# Research Pipeline

## Goal

Define a deterministic, resumable pipeline that turns heterogeneous research sources into structured, evidence-linked knowledge.

## Stages

### 1. Discover

Search configured providers and source catalogs using a reproducible `SearchStrategy`.

Outputs:

- provider records
- query execution metadata
- pagination/checkpoint state
- search snapshot

Requirements:

- provider-specific queries remain in adapter metadata
- normalized search results map into canonical `WorkCandidate` objects
- duplicate provider results are not immediately treated as duplicate works until identity resolution

### 2. Resolve

Resolve candidate records into canonical works and external identifiers.

Use deterministic identifiers first (DOI, PMID, arXiv ID, repository revision), then normalized metadata matching with confidence and reviewability.

Never silently merge ambiguous works.

### 3. Acquire

Acquire permitted artifacts such as PDFs, HTML, XML, datasets, code archives, or user uploads.

Requirements:

- compute content hash
- persist origin and acquisition metadata
- preserve HTTP/source metadata where useful
- respect robots, rate limits, credentials, terms, and configured rights policy
- distinguish discovered metadata from legally/permissibly acquired full text

### 4. Parse

Parse artifacts into the common document representation.

Parser selection should be capability-based:

- Docling-style general document parser
- GROBID-style scholarly enrichment
- native structured formats when available

A parse run records parser name, version, options, artifact hash, timing, and errors.

### 5. Normalize

Normalize structural concepts without flattening away useful hierarchy:

- headings/sections
- paragraphs/passages
- tables
- figures
- equations
- footnotes
- references/citations

Preserve source offsets/page references where possible.

### 6. Enrich

Add metadata from complementary sources without destroying source attribution.

Examples:

- DOI metadata from Crossref
- citation graph/field concepts from OpenAlex
- scholarly graph metadata from Semantic Scholar
- bibliographic extraction from GROBID

Conflicting metadata should be represented as source-attributed observations and resolved according to explicit precedence rules.

### 7. Extract

Run extraction contracts over eligible document regions.

Examples:

- claims
- hypotheses
- methods
- variables
- datasets
- software
- models
- metrics
- experiments
- results
- limitations

Extraction contracts should be versioned, schema-constrained, domain-aware, and independently testable.

### 8. Verify

Verify relationships between claims and source evidence.

Verification is a separate stage from extraction.

A verifier may classify an evidence relation as:

```text
supports
contradicts
partially_supports
qualifies
mentions
no_evidence
uncertain
```

The system records verifier version and confidence, and allows human review.

### 9. Index

Build retrieval representations:

- lexical/full-text indexes
- metadata indexes
- embeddings
- topic/concept links
- compact summaries
- hierarchical summaries

Indexing is versioned so representations can be rebuilt without re-acquiring source artifacts.

### 10. Synthesize

Build higher-level, source-linked research products such as:

- work summaries
- topic summaries
- method comparisons
- evidence maps
- contradiction clusters
- research-gap candidates
- chronology/timeline summaries

Synthesis must link to the lower-level objects used to create it.

### 11. Serve

Expose knowledge to humans and agents through stable services.

The default response should be compact. Consumers explicitly request deeper layers.

### 12. Export

Generate reusable outputs:

- Quarto projects/reports
- Markdown
- JSON/JSONL
- BibTeX/RIS
- CSV/Parquet
- downstream domain mappings

## Resumability

Every expensive stage should have an idempotency key or equivalent cache identity derived from inputs and versions.

Example:

```text
parse_key = hash(artifact_sha256, parser_name, parser_version, parser_config)
```

If the inputs have not changed, the stage should not rerun by default.

## Incremental synchronization

A subsequent sync should answer:

```text
What is new?
What changed?
What was corrected/retracted?
What newly cites existing works?
What requires re-extraction because a contract changed?
```

It should not blindly repeat the original workload.

## Failure behavior

Pipeline failures are isolated by artifact/stage where possible.

Requirements:

- durable error records
- retry classification
- exponential backoff for transient remote failures
- no corrupted partial success presented as complete
- checkpointed pagination
- dead-letter/review path for repeated failures

## Backpressure and rate limits

Providers expose capability metadata including:

- concurrency recommendations
- request quotas
- retry-after handling
- authentication requirements

The orchestrator controls pacing rather than each business workflow inventing its own retry loops.

## Human-in-the-loop checkpoints

Optional review points should include:

- ambiguous identity merges
- inclusion/exclusion screening
- extraction validation
- claim/evidence verification
- rights assessment
- high-impact synthesis

Human decisions become auditable records rather than destructive edits.

## Reproducibility snapshot

A `ResearchSnapshot` records enough state to characterize a research run:

- workspace/research questions
- source/provider set
- exact search strategies
- execution timestamps
- inclusion/exclusion policy
- discovered/included/excluded counts
- artifact hashes
- parser/extractor/verifier versions
- embedding/retrieval versions
- domain-pack version
- application git revision/release
- relevant model/provider configuration identifiers

Secrets are never stored in snapshots.

## Downstream experiment handoff

The platform should expose structured handoff objects so a domain project can convert research into executable work.

Example:

```text
Work -> Claim -> Method -> Variable -> FeatureCandidate -> ExperimentSpec
```

`FeatureCandidate` and `ExperimentSpec` may live in a domain integration rather than the universal research core, but lineage back to research objects must remain intact.
