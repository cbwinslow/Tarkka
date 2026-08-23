# Native document adapters

Tarkka prefers the richest source-native representation available and keeps the acquired artifact immutable. A parser may still produce the canonical `Document` used by existing ingest flows, but native-aware parsers should additionally expose `NativeDocumentParseResult` so bibliography, inline citation anchors, source observations, and linked resources are not discarded during normalization.

## Parser priority

Prefer a format-specific native adapter over a general reconstruction adapter when both support the same artifact. For example, JATS/NXML should be parsed as JATS rather than routed through a generic XML/PDF-to-Markdown path. Semantic HTML/XHTML is likewise preferred over a generic reconstruction path, and EPUB delegates its XHTML spine members to that shared native HTML normalization boundary.

## Current preservation matrix

| Adapter | Basis | Structure | Bibliography | Inline citations | Figures | Tables | Equations | Resource/supplement links |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| JATS | native | yes | yes | yes | yes | yes | yes | yes |
| Semantic HTML/XHTML | native | yes | yes | yes | yes | yes | MathML | yes |
| EPUB | native | package + spine | yes | yes | yes | yes | MathML | yes |
| Docling/PDF | reconstructed | yes | no | no | yes | yes | stable formula label / best effort | no |
| Plain text | reconstructed | minimal | no | no | no | no | no | no |

Capability manifests are the machine-readable source of truth. The matrix is explanatory and must not advertise a capability that the adapter manifest does not expose. Format-specific documentation records narrower preservation and safety details in `SEMANTIC_HTML.md`, `EPUB.md`, and `DOCLING_ADAPTER.md`.

## Preservation rules

- Keep canonical `Document`, `Section`, and `Passage` records provider-neutral.
- Preserve native IDs/anchors and provider metadata in `SourceObservation` instead of adding format-specific fields to the canonical schema.
- Promote figures, tables, and equations into existing first-class source-artifact contracts rather than embedding them in Markdown.
- Preserve bibliography entries and inline citation anchors through the citation contracts introduced by issue #26.
- Preserve supplementary/resource links as `ResourceLinkObservation` values.
- Label reconstructed structure as reconstructed; do not present PDF layout recovery as source-native structure.
- Use stable IDs derived from the immutable source artifact plus native anchors when the format provides durable anchors.
- Share normalization boundaries instead of duplicating them: EPUB spine XHTML reuses the semantic HTML parser rather than defining a second HTML model.
- Keep remaining format support incremental: LaTeX/source bundles and optional OCR/layout adapters should reuse these boundaries rather than redesigning the canonical schema. Bibliography interchange formats such as BibTeX, RIS, and CSL-JSON use the bibliography subsystem rather than pretending to be document adapters.

## Fixture policy

Every structure-aware adapter should have deterministic fixtures that fail if expected structure disappears. At minimum, fixtures should cover the capabilities the adapter advertises, including bibliography, citation anchors, figures, tables, equations, and resource links when supported.

Current fixture/regression coverage includes JATS native preservation, semantic HTML structure/citations/artifacts/links, EPUB package/spine preservation and archive safety, and Docling reconstructed figures/tables/formulas plus its documented upstream model contract.
