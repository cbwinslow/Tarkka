# Milestone 4 — Structured Research Extraction

## Goal

Turn normalized `Document -> Section -> Passage` content into reusable, typed research objects while preserving exact evidence and extraction provenance.

This milestone starts with contracts, not prompts. Tarkka's extraction model must work with deterministic rules, local models, cloud models, or future human-assisted workflows without changing the core domain model.

## Core separation

```text
Document
  ↓
Section
  ↓
Passage
  ↓
Evidence
  ↓
Claim / Hypothesis / Method / Dataset / Variable / Model / Metric / Result / Limitation
```

A claim is not evidence. A result is not evidence. Evidence is an addressable source-grounded span that semantic objects reference.

## Evidence contract

The first evidence locator is a passage-local text span:

- `document_id`
- `section_id`
- `passage_id`
- `passage_char_start`
- `passage_char_end`
- exact extracted text
- record-level extraction provenance

`Evidence.from_passage(...)` derives the excerpt directly from a normalized passage. `ExtractionBatch` then re-validates every evidence record against the normalized `Document`, including document/section/passage identity, range containment, and exact text equality. Fabricated or stale evidence therefore fails closed at the batch boundary.

Future table, figure, equation, page-coordinate, or source-native locators can be added without weakening the passage evidence contract.

## Run and record provenance

Run-level metadata is represented once by `ExtractionRun`:

- extraction run UUID
- extractor name
- extractor version
- extraction contract version
- optional model provider/name/version
- extraction timestamp

Record-level `ExtractionProvenance` stores:

- the parent run UUID
- confidence
- human review state
- optional short reasoning summary

This separation prevents evidence and semantic records from disagreeing about extractor/model/version metadata while still allowing confidence and review state to vary per record.

Tarkka does **not** store hidden chain-of-thought. A reasoning summary is an optional concise, user-visible explanation of why an extraction was produced.

Human review states are:

- `unreviewed`
- `verified`
- `corrected`
- `rejected`

## Attribution

Semantic objects distinguish where the interpretation comes from:

- `author_stated`
- `extractor_inferred`
- `synthesis`

This is especially important for limitations. An author-stated limitation must never silently become indistinguishable from a limitation inferred by an extractor or downstream synthesis.

## Research object kinds

The initial core contracts include:

- `Claim`
- `Hypothesis`
- `Method`
- `Dataset`
- `Variable`
- `Model`
- `Metric`
- `Result`
- `Limitation`

Each extraction has its own UUID, document identity, one or more evidence IDs, record provenance, and attribution.

The object-specific fields are intentionally small in this foundation PR. Domain packs and later extraction-contract versions should extend meaning without adding baseball-, finance-, or provider-specific fields to the generic core.

## Batch invariant

`ExtractionBatch` is one validated, non-empty extractor run over one normalized `Document`.

A batch fails closed for conditions including:

- no evidence
- no semantic extraction
- duplicate evidence IDs
- duplicate extraction IDs
- evidence from another document or run
- semantic records from another document or run
- evidence that does not resolve to a normalized passage
- evidence text/ranges that do not match the normalized passage
- an extraction that references evidence outside the batch

This makes deterministic and model-assisted extractors testable with the same fixtures.

## Extractor boundary

`StructuredExtractor` remains provider/model-neutral. `validate_extractor_output(...)` enforces the postconditions that:

- the returned batch belongs to the input `Document`
- `ExtractionRun.extractor_name` matches the extractor
- `ExtractionRun.extractor_version` matches the extractor

No model SDK appears in the contract.

## Repository boundary

`ExtractionRepository` supports document reads with optional `run_id` scoping, kind filtering for semantic records, and bounded pagination.

`save_batch()` has explicit persistence semantics:

1. persist the run, evidence, semantic records, and evidence links in one transaction
2. retrying identical content for the same `(document_id, run_id)` is a no-op
3. conflicting content for an existing `(document_id, run_id)` fails closed
4. no partial batch becomes visible

The first local/PostgreSQL implementations must prove these semantics with adapter tests.

## PostgreSQL reference model

Migration `0005_structured_extraction.sql` adds:

- `tarkka.extraction_run`
- `tarkka.evidence`
- `tarkka.research_extraction`
- `tarkka.research_extraction_evidence`

The schema uses composite lineage foreign keys so a run, evidence record, extraction, and association cannot silently cross documents or runs. A source-validation trigger checks evidence text against the normalized passage span. Deferred constraint triggers prevent a persisted semantic extraction from surviving without at least one evidence association. Run/document lookup indexes support the repository's expected access paths.

The Python domain stays strongly typed while `research_extraction.payload` remains JSONB so extraction-contract revisions and domain packs do not require one table per semantic type.

## Reproducible validation workflow

A minimal user/agent validation loop is:

1. normalize a document and select a `Passage`
2. create one `ExtractionRun`
3. create record-level `ExtractionProvenance` using that run UUID
4. construct evidence with `Evidence.from_passage(...)`
5. construct a typed semantic object that references the evidence UUID
6. build `ExtractionBatch(document=..., run=..., evidence=..., extractions=...)`
7. validate extractor postconditions with `validate_extractor_output(...)`
8. run the focused contract suite:

```bash
pytest -q tests/test_extraction_contracts.py tests/test_extraction_schema.py
```

If batch construction raises `ValueError`, inspect the reported invariant first: document/run identity, normalized passage lineage, exact span text, duplicate IDs, or missing evidence references. Reproduce failures with the smallest normalized `Document`/`Passage` fixture and the same run UUID rather than bypassing validation.

Agents should return evidence-backed records plus only concise visible reasoning summaries where useful. They must not persist hidden chain-of-thought.

## Current non-goals

This foundation intentionally does **not** add:

- an LLM SDK
- production prompts
- a concrete extraction repository adapter
- automatic document extraction orchestration

Those belong to measured vertical slices after the contracts are stable.

## Next vertical slice

After these contracts merge, the next PR should prove the model end to end with a narrow claim-extraction workflow:

```text
normalized Document
    ↓
deterministic claim extractor
    ↓
Evidence + Claim
    ↓
local ExtractionRepository
    ↓
CLI query with exact evidence expansion
```

A replaceable model-assisted adapter should follow only after the deterministic path establishes persistence and evaluation behavior.

## Invariants

1. Important semantic records must be evidence-backed.
2. Evidence must resolve to a precise normalized source location.
3. Extractor/model/version information must remain auditable at run scope.
4. Confidence and human review state remain auditable per record.
5. Author-stated and inferred interpretation remain distinct.
6. Core extraction contracts do not depend on a model provider or domain pack.
7. Hidden chain-of-thought is never persisted.
