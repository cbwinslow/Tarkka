# Docling adapter compatibility contract

Tarkka treats Docling as an optional adapter behind the parser port. Importing Tarkka must not require Docling, and injected converters remain supported for deterministic tests.

## Supported Docling v2 surface

The adapter intentionally depends on a small, documented subset of the `DoclingDocument` model:

- conversion result: `.document`
- document: `.export_to_markdown()`, optional `.name`
- document collections: optional `.pictures`, `.tables`, `.texts`
- picture items: optional `.label`, `.caption`, `.prov`
- table items: optional `.label`, `.caption`, `.data`, `.prov`
- table data: optional `.num_rows`, `.num_cols`
- text/formula items: `.label`, optional `.text`, optional `.prov`
- provenance: first `.prov` item may expose `.page_no`

Missing optional collections are treated as empty. Missing, malformed, negative, or non-integer page/table dimensions are represented as `None`; Tarkka does not invent structural values.

## Formula detection

Current Docling v2 exposes formula text items through the stable `DocItemLabel.FORMULA` value `"formula"`. Tarkka therefore recognizes formulas only when the item's label value is exactly `formula` after case/whitespace normalization. Both the real enum-like `.value` form and a plain string are accepted so injected test adapters remain lightweight.

Substring heuristics such as `"equation" in label` are intentionally not supported because they can classify unrelated or future labels as equations.

## Representation boundary

Docling structure is marked `RECONSTRUCTED`, not native. Markdown exported by Docling is normalized through Tarkka's Markdown hierarchy, while pictures, tables, and formulas are preserved as first-class Tarkka artifacts when the supported fields above are present.

Raw acquired source bytes remain immutable. NUL bytes observed in reconstructed Markdown are replaced before downstream storage to avoid silent truncation in external systems.

## Upgrade policy

When upgrading Docling or `docling-core`, run both the regular unit suite and the Docling integration workflow. If upstream changes any field listed above, update this contract and its regression tests in the same change rather than adding broad reflection or silent fallbacks.
