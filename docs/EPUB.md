# EPUB ingestion

Tarkka treats EPUB as a source-native container rather than flattening the whole book through a generic conversion step.

## Preserved structure

`EpubParser` reads the EPUB package document and preserves:

- package metadata such as title, language, identifiers, creators, publisher, dates, rights, subjects, and modification time;
- the package manifest and spine in source order;
- linear spine reading order;
- package resource relationships and media types;
- semantic XHTML structure from each linear spine item using the existing `SemanticHtmlParser`;
- figures, tables, MathML equations, bibliography entries, inline bibliography mentions, and semantic resource links exposed by spine XHTML.

The resulting canonical `Document` represents the linear EPUB reading order. IDs are deterministic from the immutable EPUB artifact plus package/spine identity, and passage character offsets are rebased into one document-wide coordinate space. As elsewhere in Tarkka normalization, adjacent passages use an implicit one-character separator in that coordinate space so passage ranges never overlap.

## Source preservation

The original EPUB bytes remain in the artifact store. Package/container details that do not belong in the provider-neutral `Document` schema remain in `SourceObservation.metadata`.

XHTML spine items are decoded from BOM or declared XML/HTML character encoding when present, normalized to UTF-8 temporary text, and passed through `SemanticHtmlParser`. Archive member paths are never extracted directly onto the filesystem.

Package-manifest resource observations and XHTML-discovered links remain separate observations even when they target the same resource, because they carry different source-native provenance and metadata.

## Safety and fail-closed behavior

The parser:

- requires the EPUB `mimetype` entry to be first, uncompressed, and exactly `application/epub+zip`;
- rejects encrypted archive entries;
- rejects absolute paths, parent-directory traversal, encoded traversal, and backslash archive paths;
- caps archive entry count, total uncompressed size, package XML size, and individual spine-member size;
- rejects missing manifest resources and unknown spine references;
- rejects unsupported media types when they appear in the linear spine instead of silently dropping reading-order content;
- parses XML/XHTML as data and does not execute scripts or active content.

## Current scope

The first EPUB adapter intentionally supports linear `application/xhtml+xml` and `text/html` spine content. Non-linear spine entries remain represented in the source-native spine metadata and as related resource observations, but they are not added to canonical reading order.

Binary package resources such as images, fonts, audio, and video are preserved as resource observations; they are not yet promoted into separate stored `Artifact` records by the EPUB parser. External or intra-package links discovered inside XHTML are preserved when the semantic HTML adapter recognizes their relation.

EPUB-specific navigation documents, page lists, media overlays, rendition metadata, accessibility metadata, and EPUB CFI resolution can be added later without changing the canonical parser boundary.
