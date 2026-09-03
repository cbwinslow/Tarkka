# OCR, Conversion Quality, and Derived Representations

## Purpose

Scanned pages, photographs, PDFs, tables, formulas, and complex layouts are valuable research
sources even when they lack reliable machine-readable text. Tarkka must make their reconstruction
useful without confusing it with what the source natively encoded.

## Preservation and provenance

The original image/PDF remains an immutable Artifact. OCR, layout detection, table reconstruction,
formula recognition, page rendering, and vision descriptions are separate derived observations or
derivative Artifacts. Each records:

- input Artifact digest and source/page/region locator;
- adapter/engine name, version, model files, language configuration, and material options;
- execution time, failure outcome, and bounded diagnostic metadata;
- native, reconstructed, or inferred basis;
- output digest/reference when bytes or a large payload are produced.

No derived text may overwrite native embedded text, and no model/vision interpretation may be stored
as an OCR fact. A document can have multiple competing derivations; selection is an application
policy decision, not destructive replacement.

## Quality report

Every conversion-capable adapter should expose a versioned report at document and page/region level.
It contains observable dimensions, not a single claim of truth:

- OCR/text-recognition confidence and language coverage;
- layout/reading-order confidence;
- table/formula/figure extraction confidence where available;
- input diagnostics such as page count, resolution, rotation/skew, image-only detection, and
  existing-text-layer status;
- warnings, skipped regions, timeout/limit outcomes, and review recommendation;
- adapter/model/version and quality-policy version.

Adapter-native confidence scores are retained as observations. Tarkka may map them into a stable
grade such as `excellent`, `good`, `fair`, `poor`, or `unknown`, but must retain the originating
metric/version and never compare raw scores from unrelated engines as though they were calibrated.

The adapter-neutral derivation contract identifies both the derivation and its source Artifact.
Its reconstructed Document must refer to that same source Artifact, while using derivation-scoped
identities so it cannot overwrite a native or competing reconstructed Document. Page-quality records
use 1-based source page numbers as their initial locators; richer region locators remain additive.

## Quality gates

Quality gates decide what happens next; they do not erase data.

```text
original Artifact
  -> native text available? preserve it
  -> OCR/layout derivation
  -> quality report
  -> accept for unattended indexing | retain with warning | require review | retry alternative adapter
```

Gates are configurable by workspace/domain policy. Low quality may prevent automated claim
extraction or similarity indexing while still allowing a user to inspect the original and derived
text. The gate decision itself is an auditable observation.

## Reusable adapters, not reinvention

Use mature engines behind narrow contracts. Candidate implementations include Docling for structured
conversion/confidence reporting, OCRmyPDF/Tesseract for local PDF/image OCR, and specialized
formula/table/vision adapters when a measured workflow justifies them. Every dependency remains
replaceable, optional where practical, license-reviewed, and tested with deterministic fixtures.

## Initial implementation boundary

Do not create a mandatory cloud OCR service, mutate originals into OCR PDFs, or implement a new OCR
engine. Start with one local/offline reference adapter, a stable quality report, representative
multilingual/scanned/table-heavy fixtures, and explicit human-review routing.
