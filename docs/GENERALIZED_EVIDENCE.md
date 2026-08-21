# Generalized Evidence

Tarkka evidence can cite normalized text, figures, table regions, and equations without treating OCR or model interpretation as part of the core domain contract.

## Source artifacts

A normalized `Document` may own immutable source observations:

- `Figure`
- `Table`
- `Equation`

These objects describe what the parser observed in the source document. They do not contain conclusions inferred by an LLM or vision model.

```text
Document
├─ Section -> Passage
├─ Figure
├─ Table
└─ Equation
```

OCR, chart digitization, vision interpretation, and embeddings remain optional adapters layered on top of these source artifacts.

## Evidence locators

The typed locator vocabulary is:

- `PassageSpan(section_id, passage_id, char_start, char_end)`
- `FigureRef(figure_id)`
- `TableCellRange(table_id, row_start, row_end, column_start, column_end)`
- `EquationRef(equation_id)`

Table ranges use zero-based, half-open row and column coordinates.

Existing passage `Evidence` remains source-compatible and exposes a `PassageSpan` through its `locator` property. Non-text sources use `FigureEvidence`, `TableEvidence`, and `EquationEvidence`. `EvidenceRecord` is the common typed union used by extraction batches and repositories.

## Resolution and failure behavior

An `ExtractionBatch` resolves every evidence record against the owning normalized `Document`.

It fails closed when:

- evidence belongs to another document or extraction run
- a passage or source artifact ID is unknown
- passage text or offsets do not match the normalized source
- a table range exceeds known table dimensions
- an extraction references an evidence ID outside its batch

Unknown table dimensions do not make a valid non-empty range invalid; parsers may discover dimensions later. When dimensions are known, bounds are enforced.

## Artifact versus interpretation

A source artifact is not itself an inference.

```text
Figure / Table / Equation
        ↓
optional observation adapter
        ↓
optional interpretation
        ↓
Claim / Result / Method / Dataset / other research object
```

For example, `Figure 3 exists on page 8 with caption X` is source provenance. `Figure 3 shows that Y increases with X` is an interpretation and must retain extractor/model provenance and review state.

Interpretations never overwrite immutable source artifacts.

## Persistence

The local JSON extraction repository writes a `source_kind` discriminator for new evidence records. Existing schema-v1 JSON passage evidence without `source_kind` is still read as passage evidence.

PostgreSQL migration `0006_generalized_evidence.sql` adds source-artifact tables and generalizes the existing `tarkka.evidence` table while preserving extraction-run/document lineage and the existing extraction-to-evidence link table.

## Current non-goals

This contract does not yet:

- parse figures/tables/equations from Docling output
- run OCR
- run a vision model
- digitize chart pixels into numerical series
- embed image content
- infer scientific meaning from a figure or table

Those capabilities can be added as adapters without changing the core provenance boundary.
