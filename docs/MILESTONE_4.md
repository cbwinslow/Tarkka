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
- extraction provenance

`Evidence.from_passage(...)` validates that the requested span is contained within the normalized passage and derives the exact excerpt from the passage text.

Future table, figure, equation, page-coordinate, or source-native locators can be added without weakening the passage evidence contract.

## Extraction provenance

Every evidence-backed extraction records:

- extraction run UUID
- extractor name
- extractor version
- extraction contract version
- optional model provider/name/version
- confidence
- human review state
- extraction timestamp
- optional short reasoning summary

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

Each extraction has its own UUID, document identity, one or more evidence IDs, provenance, and attribution.

The object-specific fields are intentionally small in this foundation PR. Domain packs and later extraction-contract versions should extend meaning without adding baseball-, finance-, or provider-specific fields to the generic core.

## Batch invariant

`ExtractionBatch` is the unit returned by one extractor call for one normalized document.

A batch fails closed when:

- evidence belongs to another document
- evidence IDs are duplicated
- an extraction belongs to another document
- an extraction references evidence not included in the batch

This makes it possible to validate deterministic and LLM-assisted extractors with the same fixtures.

## Ports

`StructuredExtractor` is the provider/model-neutral extraction boundary:

```python
class StructuredExtractor(Protocol):
    name: str
    version: str

    def extract(self, document: Document) -> ExtractionBatch: ...
```

`ExtractionRepository` is the persistence boundary for saving batches and retrieving evidence/extractions by document and kind.

No model SDK appears in either contract.

## PostgreSQL reference model

Migration `0005_structured_extraction.sql` adds:

- `tarkka.extraction_run`
- `tarkka.evidence`
- `tarkka.research_extraction`
- `tarkka.research_extraction_evidence`

The Python domain stays strongly typed while `research_extraction.payload` remains JSONB so extraction-contract revisions and domain packs do not require one table per semantic type.

## Next vertical slice

After these contracts merge, the next PR should prove the model end to end with a narrow claim-extraction workflow:

```text
normalized Document
    ↓
claim extractor
    ↓
Evidence + Claim
    ↓
ExtractionRepository
    ↓
CLI/API query with exact evidence expansion
```

The first implementation should favor a deterministic fixture/rule extractor plus one replaceable model-assisted adapter rather than making an LLM mandatory.

## Invariants

1. Important semantic records must be evidence-backed.
2. Evidence must resolve to a precise normalized source location.
3. Extractor/model/version information must remain auditable.
4. Human review state is explicit.
5. Author-stated and inferred interpretation remain distinct.
6. Core extraction contracts do not depend on a model provider or domain pack.
7. Hidden chain-of-thought is never persisted.
