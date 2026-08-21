# Semantic HTML preservation

Tarkka prefers source-native HTML semantics over generic document reconstruction when the input is HTML or XHTML.

`SemanticHtmlParser` preserves:

- heading hierarchy and native read order
- paragraph/list/quote/preformatted text blocks
- DPUB bibliography entries and inline bibliography references
- semantic figures and captions
- table dimensions and captions
- MathML equations
- scholarly `<meta>` fields such as `citation_title` and `citation_doi`
- canonical, alternate, supplement, dataset, and software resource links

The adapter returns `NativeDocumentParseResult`, so provider-specific metadata stays in `SourceObservation` while `Document`, `Section`, `Passage`, citation records, and source-artifact records remain provider-neutral.

IDs are deterministic for the same immutable artifact. HTML/XHTML is registered ahead of Docling in the CLI parser order so native semantics are not flattened through a reconstructed Markdown representation first.

EPUB should reuse this parser for XHTML spine documents rather than creating a second HTML normalization path.
