# Citation context anchoring

Tarkka preserves document-local citation context separately from bibliography references and canonical Work resolution.

## Context contract

A `CitationContext` records the full normalized passage containing one `CitationMention`, including the passage text, exact document character range, section ID, and passage ID. Context IDs are deterministic from the mention and passage IDs.

Native parsers may provide contexts directly when the source format exposes exact structural anchors. Parser-provided contexts with a `passage_id` must exactly match that normalized passage's text, section, and character range. A native parser may omit `passage_id` only when it is preserving a source-local context window that has not yet been mapped to a normalized passage.

When a parser provides citation mentions with missing contexts, ingest preserves its supplied contexts and applies the conservative fallback only to uncovered mentions:

1. an explicit `passage_id` is honored only when that passage exists, contains the mention text, and any supplied mention character bounds agree with the anchored passage;
2. otherwise the mention text must occur exactly once, including overlapping occurrences, in exactly one normalized passage;
3. repeated or ambiguous marker text produces no automatic context.

The fallback never performs fuzzy matching, nearest-text guessing, or global semantic inference. Callers that need unanchored-mention observability can compare the mention IDs in a parse with the mention IDs represented by returned contexts.

## Persistence

`NativeDocumentParseResult` carries references, mentions, contexts, and resource links together with the normalized `Document` and source observation. Ingest validates that contexts belong to the parsed document and reference parsed mentions/passages before persisting them to the citation repository.

This keeps citation evidence traceable through:

`source document -> citation mention -> citation context -> bibliography reference -> canonical Work`

That chain is the foundation for later citation-support and claim-verification workflows.

## CLI disclosure boundary

The local CLI exposes this chain without returning an entire bibliography or document by default:

```bash
tarkka citations list <document-id> --offset 0 --limit 20
tarkka citations show <document-id> <reference-id>
tarkka citations resolve <document-id>
```

`list` returns bounded reference metadata and stable IDs (at most 100 records per request), but
omits raw bibliography text and context passages. `show` expands exactly one reference, its
recorded resolution state when one exists, and only the citation mentions/contexts tied to that
reference. Inspection never initializes a missing local citation catalog. This is a local interface
over the existing citation repository. `resolve` performs exact identity resolution but does not
infer evidentiary support; it also processes a bounded reference page (at most 100) per request.
