# Artifact Composition and Portable Exports

## Purpose

Tarkka must preserve an acquired source exactly while allowing people and agents to address,
select, rearrange, and export useful parts of its derived structure. Examples include a formula
sheet assembled from several equity-analysis documents, a table appendix, or an evidence package
for a research question.

## Non-negotiable preservation boundary

The acquired `Artifact` is the exact source representation. It is content-addressed and retained
unchanged. A normalized `Document`, OCR text, page image, table extraction, or selected component
is a derived representation; it must never claim to reconstruct the original binary byte-for-byte.

Exact recovery means retrieving the retained original Artifact by digest. Reproducible composition
means replaying a versioned selection/export recipe against identified Artifact/Document versions.
Those are different guarantees.

```text
exact source bytes ──> Artifact (sha256)
                           │
                           ├──> Document (parser + version)
                           │       └──> addressable components/locators
                           ├──> OCR/layout/vision derivations
                           └──> composition manifest ──> derivative export (sha256)
```

## Addressable components

Components are logical source locations, not automatically independent files. They may identify a
section, passage, page region, figure, table/cell, equation, bibliography entry, citation context,
or linked resource. A component reference must retain enough information to be replayable:

- source Artifact digest and, when applicable, normalized Document ID/version;
- component type and stable ID/native anchor or deterministic parser locator;
- page/layout coordinates or source offsets when available;
- native/reconstructed/inferred basis;
- parser/OCR/extractor version and transformation parameters when derived.

The system should preserve the richest native representation first. It may materialize a component
as its own derivative Artifact only when a consumer needs independently portable bytes (for example,
a rendered page image or exported table), not merely because it can split a document.

## Composition manifest

A composition is a versioned, append-only manifest, not an edit of its inputs. It should record:

- selected component references in explicit order;
- permitted transformations (for example, crop, render, redact, transcode, or layout template);
- export format/profile and renderer version;
- input Artifact digests and derived-representation versions;
- title/attribution/citation choices and omission rationale where relevant;
- rights/access decision for the requested output;
- resulting derivative Artifact digest, size, and creation provenance.

The manifest makes a formula PDF or evidence packet portable and reproducible while retaining the
source-level provenance for every included component. It must expose stable handles to agents and
people before delivering large export bytes.

## Export rules

- Exporters are replaceable adapters behind an application service; CLI, REST, MCP, and SDK must
  use the same composition service.
- Preserve source attribution and locators by default. An export may summarize or render content,
  but must identify the input representation and transformation.
- Rights to acquire or store an Artifact do not imply rights to redistribute a composed export.
- Do not flatten source-native, reconstructed, and inferred material into one unlabeled output.
- Exports that rely on model-generated prose must retain model/version/prompt-contract provenance
  and clearly label the prose as inferred.

## Initial implementation boundary

Do not build a general WYSIWYG document editor or require physical partitioning of every format.
First implement a small composition service over existing addressable components and one deterministic
export format. Add format-specific renderers only after representative fixtures prove source
locators, ordering, attribution, and rights behavior.

### V1 section-only implementation

The initial service composes reconstructed `Section` objects only. Each immutable manifest component
pins the source Artifact SHA-256, Document ID, Section ID, parser name/version, and reconstructed
basis; a manifest also pins the Markdown renderer name/version, explicit component order, and an
auditable decision permitting or denying redistribution. The service can first inspect these stable
source locators, then resolve and render them through a replaceable exporter boundary.

The first exporter produces deterministic UTF-8 Markdown with per-section source attribution. Its
output receipt records the composition/revision, output SHA-256, byte size, media type, filename,
and export time. Export bytes and receipts are returned as a derived result; this V1 service does
not yet persist them as an Artifact or alter any source Artifact. A denied right, missing/stale
source, missing exporter, or rendering interruption returns a typed failure before any source
mutation.

## Required tests

- exact original Artifact retrieval is unaffected by parsing/export;
- a composition manifest reproduces the same selected inputs and ordering;
- a changed parser/OCR/exporter version produces a distinct, explainable derived result;
- every exported component resolves to its source Artifact and locator;
- policy/rights denial, missing input, and interrupted export have typed, non-destructive behavior.
