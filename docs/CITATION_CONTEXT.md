# Citation context anchoring

Tarkka preserves document-local citation context separately from bibliography references and canonical Work resolution.

## Context contract

A `CitationContext` records the normalized passage surrounding one `CitationMention`, including the passage text, exact document character range, section ID, and passage ID. Context IDs are deterministic from the mention and passage IDs.

Native parsers may provide contexts directly when the source format exposes exact structural anchors. When a parser provides citation mentions but no contexts, ingest applies a conservative fallback:

1. an explicit `passage_id` is honored only when that passage exists and contains the mention text;
2. otherwise the mention text must occur exactly once in exactly one normalized passage;
3. repeated or ambiguous marker text produces no automatic context.

The fallback never performs fuzzy matching, nearest-text guessing, or global semantic inference.

## Persistence

`NativeDocumentParseResult` carries references, mentions, contexts, and resource links together with the normalized `Document` and source observation. Ingest validates that contexts belong to the parsed document and reference parsed mentions/passages before persisting them to the citation repository.

This keeps citation evidence traceable through:

`source document -> citation mention -> citation context -> bibliography reference -> canonical Work`

That chain is the foundation for later citation-support and claim-verification workflows.
