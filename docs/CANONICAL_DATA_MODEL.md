# Canonical Research Data Model

## Purpose

The canonical model is the interoperability boundary of the platform. External sources may use different schemas, identifiers, and terminology, but adapters normalize them into stable internal concepts.

The model must support both scholarly and non-scholarly research while preserving uncertainty and provenance.

## Identity model

Prefer stable external identifiers when present, but never make any single provider identifier the primary identity of a work.

Possible identifiers include:

- DOI
- OpenAlex ID
- Semantic Scholar ID
- arXiv ID
- PMID / PMCID
- ISBN
- repository URL + revision
- dataset DOI
- vendor/institution identifier

Store identifiers as typed aliases to a canonical internal UUID.

`Work.external_ids` preserves provider/exchange metadata needed for lossless Work round trips, but it is not the canonical identity index. Normalized lookup, uniqueness, and conflict detection belong to first-class `WorkIdentifier` aliases (`tarkka.work_identifier` in PostgreSQL). Backends must preserve both without treating the metadata mapping as a substitute for the normalized relation.

## Core entities

### Workspace

A bounded research environment.

Key fields:

- `workspace_id`
- `name`
- `description`
- `domain_pack`
- `created_at`
- `settings`

### ResearchQuestion

A question or hypothesis driving discovery and synthesis.

- `question_id`
- `workspace_id`
- `text`
- `status`
- `parent_question_id`
- `created_at`

### SearchStrategy

A reproducible description of discovery intent.

- query text/terms
- providers
- filters
- date range
- language
- inclusion/exclusion rules
- execution version

### Source

Describes where metadata or content originated.

Examples: OpenAlex, Semantic Scholar, Crossref, local upload, website, institutional repository.

### Work

The intellectual/research object independent of a particular file copy.

Examples: article, report, book/chapter, thesis, standard, dataset publication, blog research post.

Suggested fields:

- canonical title
- abstract/summary when legally/technically available
- publication type
- publication date
- venue
- language
- peer-review state if known
- retraction/correction state if known
- open-access state

### Artifact

A concrete byte-level representation of a work or supporting resource.

Examples: PDF, HTML snapshot, XML, DOCX, CSV, image, source archive.

Important fields:

- content hash
- MIME type
- size
- origin URL/path
- acquired_at
- storage location
- rights metadata

### Document

A normalized parse of an artifact.

A document can be regenerated using a different parser/version without changing the artifact.

### Section

Hierarchical structural element with stable parent ordering.

### Passage

Addressable textual evidence unit. Passage boundaries should be deterministic for a given parser/chunking version when possible.

A passage is not merely an embedding chunk; it is a citable location in normalized content.

### Figure / Table / Equation

Structured document children with captions, locations, and extracted representations where available.

### Person / Organization

Authors, institutions, publishers, sponsors, data providers, and other relevant parties.

## Research semantics

### Claim

A proposition attributed to a work, author, or generated synthesis.

Do not conflate a claim with evidence.

Suggested fields:

- normalized text
- claim type
- scope/population
- directionality when relevant
- extraction confidence
- human verification state

### Evidence

A source-grounded object supporting evaluation of a claim.

Usually references one or more passages/tables/figures/results.

### EvidenceRelation

Connects a claim to evidence with an explicit relation:

- `supports`
- `contradicts`
- `partially_supports`
- `qualifies`
- `mentions`
- `no_evidence`
- `uncertain`

Store verifier, model/tool version, confidence, reasoning summary (not hidden chain-of-thought), and human-review state.

### Hypothesis

A testable proposition stated by a source or created in a downstream research workflow.

### Method

A reusable methodology or technique.

Examples:

- hierarchical Bayesian regression
- randomized controlled trial
- XGBoost classification
- event study
- Elo rating

### Model

A statistical, machine-learning, econometric, physical, or conceptual model used in research.

### Variable

An input, outcome, control, feature, covariate, or latent construct.

### Metric

A measured evaluation quantity such as log loss, RMSE, Sharpe ratio, effect size, confidence interval, calibration error, or accuracy.

### Dataset

A dataset referenced or used by a work. May resolve to a separate stored artifact or external source.

### Software

Code, package, repository, executable, or environment used by a study.

### Experiment

A source-reported or locally reproduced experiment.

### Result

A structured outcome linked to experiment/method/model/metric.

### Limitation

A stated or inferred limitation. Inferred limitations must be explicitly distinguished from author-stated limitations.

### Concept / Entity

Normalized semantic concepts that support domain packs, linking, filtering, and retrieval.

## Provenance model

Every important derived record should be able to answer:

- What source artifact led to this?
- Which location in that source supports it?
- Which parser/extractor produced it?
- Which version/configuration was used?
- Was an LLM involved?
- Was it reviewed or corrected by a human?
- When was it produced?

Use append-oriented provenance/audit events instead of overwriting history where practical.

## Rights model

Rights metadata is not a single `license` string.

Model independently when known:

- source license
- access basis
- storage permission
- transformation permission
- redistribution permission
- commercial-use permission
- attribution requirement
- expiration/embargo
- policy/source terms URL/reference
- rights assessment state

Unknown must remain `unknown`, not silently become permitted.

## Research quality observations

Do not create a magical universal quality score as the source of truth.

Store observable dimensions such as:

- publication/review type
- sample size
- study design
- data availability
- code availability
- replication status
- preregistration
- conflict-of-interest statement
- correction/retraction state
- domain-specific bias/leakage observations

Domain packs may define transparent scoring/ranking policies over these dimensions.

## Versioning

Objects that are derived or interpreted should support version history or immutable revisions where feasible:

- normalized document version
- extraction contract version
- claim revision
- synthesis revision
- embedding version
- quality-policy version

## Domain extensions

Do not add fields such as `pitcher_id` or `security_ticker` to core entities.

Domain packs should extend via:

- typed domain entities/relations
- namespaced attributes
- domain mapping tables
- extraction schemas
- downstream integration adapters

Examples:

```text
baseball: pitcher, batter, game, park, wOBA, FIP
finance: security, issuer, factor, alpha, beta, duration
```

## Agent-facing representation

Every major entity should support at least three representations:

1. **manifest** — ID, type, title/label, compact metadata, estimated size/cost
2. **summary** — normalized concise representation
3. **full** — complete structured object and/or source content references

This representation ladder is fundamental to progressive disclosure and token efficiency.
