# Source and Document Preservation

## Purpose

Tarkka must preserve research information across changing providers, document formats, parsers, crawlers, and extraction engines without turning any one external representation into the architecture.

The governing rule is:

> **Preserve native structure first; normalize second; infer last.**

A parser, crawler, or metadata connector may understand only part of what a source provides today. Tarkka should retain enough source-native information to revisit that observation later as adapters improve.

## Three truth layers

Every structured observation should make its basis explicit.

1. **Native** — explicitly encoded by the source, such as JATS elements, EPUB navigation, Crossref metadata, OpenAlex IDs, HTML links, or a provider-declared citation relation.
2. **Reconstructed** — detected from an imperfect representation, such as PDF layout, a caption region, OCR text, inferred reading order, or a parser-reconstructed table.
3. **Inferred** — interpreted by a model or analytical process, such as a chart trend, semantic claim, research method classification, or resolved relationship with uncertainty.

These layers may refer to one another but must not overwrite one another.

```text
native artifact / provider payload
        ↓
source observation
        ↓
reconstructed document observation (optional)
        ↓
canonical Tarkka records
        ↓
inferred research objects
```

## Source observations

`SourceObservation` is the generic provenance envelope for information received from an external source or produced by a replaceable adapter.

It records:

- source/adapter name and optional version
- native, reconstructed, or inferred basis
- provider-native record identifier when available
- media type when relevant
- optional immutable artifact reference for raw/large payloads
- bounded JSON-like native metadata
- observation timestamp

Canonical records should promote stable, useful fields into typed domain models. Provider-specific or not-yet-modeled information remains attached to the observation instead of forcing either schema churn or information loss.

This is not an "everything JSON" design. Canonical identity, evidence, documents, research objects, and relationships remain typed. Native metadata is the preservation envelope for information that has not been promoted yet.

### Existing `WorkSourceRecord`

`WorkSourceRecord` remains supported for the current scholarly discovery workflow. It is a specialized observation containing a normalized `DiscoveryRecord`.

Migration should be incremental:

```text
provider response
    ↓
SourceObservation (native payload + provenance)
    ↓
DiscoveryRecord / canonical fields
    ↓
WorkSourceRecord (current compatibility path)
```

Do not rewrite existing providers merely to adopt the generic envelope. New or materially upgraded adapters should preserve native observations first, then existing providers can migrate when touched.

## Capability manifests

Adapters expose small provider-neutral manifests rather than requiring application code to branch on implementation names.

Capability families include:

- discovery search and record lookup
- outgoing references and incoming citations
- full-text and supplement resolution
- native metadata
- document metadata and structure
- bibliography and inline citations
- figures, tables, and equations
- web, sitemap, feed, and link discovery

A manifest may also advertise media types and identifier schemes.

Application orchestration should ask:

```text
Which adapters support REFERENCES_OUTBOUND?
Which parsers support BIBLIOGRAPHY + INLINE_CITATIONS?
Which resolvers support FULL_TEXT for this identifier/media type?
```

not:

```text
if provider == "openalex": ...
elif provider == "crossref": ...
```

Capability manifests are deliberately small and agent-friendly. They do not replace richer provider documentation or configuration.

## Document formats

Tarkka should exploit native structure whenever a format provides it.

### Preferred structural representations

When multiple representations of the same Work are available, a richer native representation can be preferred for structure while all acquired artifacts remain preserved.

Examples:

- **JATS/XML** — article metadata, sections, bibliography, inline citation anchors, figures, tables, equations, footnotes, related material, and supplements.
- **EPUB** — package metadata, manifest, spine/reading order, navigation, XHTML/SVG resources, images, and semantic structure.
- **HTML/XHTML** — headings, semantic elements, links, metadata, structured data, figures, tables, and embedded resources.
- **LaTeX/source bundles** — labels, references, bibliography sources, equations, figures, tables, and source file relationships.
- **PDF** — immutable publication representation whose structure often must be reconstructed from layout; native embedded metadata should still be retained.
- **scanned PDF/images** — source artifacts first; OCR/layout/vision are optional reconstructed/inferred adapters.

PDF is not automatically the best structural source simply because it is common.

### Document observations to preserve

As adapters mature, normalized documents should be able to retain or link:

- metadata
- sections and reading order
- paragraphs/passages
- lists
- footnotes/endnotes
- figures and captions
- tables, cells, headers, notes, and captions
- equations and labels
- bibliography entries
- inline citation mentions and their contexts
- internal cross-references
- annotations where source-native
- supplementary resources
- native IDs/anchors
- page/layout coordinates when reconstructed or encoded

## Resource links

`ResourceLinkObservation` preserves a source-observed URI relationship before Tarkka resolves that target into a canonical Work or Artifact.

Examples:

- canonical/alternate representation
- full text
- supplementary CSV/XLSX/PDF
- dataset
- software/code repository
- cited resource
- version
- correction/retraction
- other related resource

Resolution is a separate concern. Observing `https://example.org/data.csv` does not mean Tarkka has acquired it, established its identity, or decided it is safe/allowed to fetch.

## Research packages and supplements

A scholarly Work may be represented by a package of related resources:

```text
Work
 ├ article XML
 ├ publication PDF
 ├ supplement PDF
 ├ data CSV/XLSX
 ├ code archive/repository
 ├ figures
 └ other supporting assets
```

Tarkka should preserve those relationships before deciding which resources to acquire or parse. A future `ResearchPackage` abstraction may group resolved resources once real workflows justify it; `ResourceLinkObservation` is the smaller primitive needed first.

When a figure/table links to underlying supplementary data, prefer the underlying data over pixel-based reconstruction while retaining the original figure/table artifact.

## Citations and bibliography

Citation handling is a distinct subsystem, not a field on a Claim.

Future contracts should distinguish at least:

- `BibliographicReference` — the bibliography entry as represented by the source
- `CitationMention` — an inline marker such as `[12]` or `Smith et al. (2024)`
- `CitationContext` — source-local context surrounding a mention
- resolved citation relation — mapping a reference to a canonical Tarkka Work
- Work-to-Work relationship — typed relation with source/provenance

This enables research traversal and later verification:

```text
claim/context in Work A
    ↓ cites
bibliographic reference
    ↓ resolve
Work B
    ↓
evidence/method/dataset in Work B
```

Citation graph expansion must always be bounded by explicit depth/work/request/byte/time policies.

## Versions, corrections, and retractions

Artifact bytes are immutable; scholarly Works can evolve.

Preserve provider/source observations for:

- preprint/published relationships
- versions
- corrections
- retractions
- translations/reviews where relevant

Do not model a correction by mutating the historical artifact or provider observation.

## Web crawling

The crawler is an acquisition/discovery adapter, not a research parser.

```text
URL discovery
    ↓
HTTP fetch/observation
    ↓
content identification
    ↓
resource-link discovery
    ↓
media/format routing
    ↓
specialized parser or artifact-only preservation
```

Crawler responsibilities may include:

- canonical URL and redirects
- HTTP metadata
- sitemap/feed origin
- internal/outbound links and anchor/context
- media type and content disposition
- structured page metadata
- publication/update timestamps when explicitly encoded
- bounded crawl state/checkpoints

The crawler must not create canonical Works merely because it found a URL. Identity resolution and research semantics remain separate application concerns.

### Bounded traversal

Crawler and citation expansion policies should expose explicit budgets such as:

- maximum depth
- maximum resources/works
- maximum requests
- maximum bytes
- allowed domains/schemes
- retry/rate policies
- optional elapsed-time budget

## Adapter extensibility

New sources should be easy to add through narrow ports and capability manifests.

Conceptually:

```text
Discovery adapters  Acquisition adapters  Document adapters  Enrichers
        \                  |                  /              /
         \                 |                 /              /
                  Tarkka contracts
                        ↓
                canonical domain
```

Adapters do not call one another directly. Application services compose capabilities.

A future explicit registry can use Python entry points after the capability contracts have been exercised by multiple real adapters. Do not add filesystem magic or a heavyweight plugin framework before then.

## Provider/source inventory

When adding or upgrading a source adapter, audit what the source exposes before choosing the normalized mapping.

Questions to answer:

1. Which stable identifiers are available?
2. Does the provider expose outgoing references or incoming citations?
3. Are authors, organizations, funders, awards, licenses, topics, versions, corrections, or retractions available?
4. What alternate/full-text/supplement/dataset/software links exist?
5. Is there a raw/native payload worth retaining?
6. Which fields are source-native facts versus provider inference?
7. What pagination, rate-limit, cursor, update, and deletion semantics exist?
8. What rights/access constraints attach to retrieval, storage, extraction, and redistribution?

The adapter's contract tests should freeze representative provider payloads so future adapter changes do not silently drop previously preserved fields.

## Testing strategy

Maintain deterministic fixture corpora for both provider responses and document formats.

Suggested document fixtures as support is implemented:

```text
tests/fixtures/documents/
  scientific-jats.xml
  structured.epub
  semantic.html
  citations.pdf
  table-heavy.pdf
  equation-heavy.pdf
  scanned.pdf
  latex-paper/
  supplements/
```

Suggested provider fixtures:

```text
tests/fixtures/providers/
  openalex-work.json
  crossref-work.json
  arxiv-entry.xml
  semantic-scholar-work.json
  future-datacite.json
  future-pubmed.xml
```

Contract tests should assert preservation, not merely successful parsing.

## Non-goals for the preservation-contract slice

Do not yet:

- rewrite all existing provider adapters
- implement OCR/vision/chart digitization
- introduce Neo4j or another graph database
- introduce a heavyweight plugin runtime
- force every provider field into relational columns
- make all canonical data generic JSON
- recursively crawl citations or websites without bounded policies

The purpose of this stage is to make those future capabilities additive rather than architectural rewrites.
