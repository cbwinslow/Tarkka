# Connector and Plugin Specification

## Purpose

The platform should gain capabilities through narrow interfaces rather than accumulating source-specific logic throughout the codebase.

The preservation rule for all adapters is:

> **Preserve native structure first; normalize second; infer last.**

Before normalizing an external source, adapters should retain a `SourceObservation` or immutable artifact reference for provider-native information that Tarkka does not yet model canonically. See [`SOURCE_DOCUMENT_PRESERVATION.md`](SOURCE_DOCUMENT_PRESERVATION.md).

## Capability-aware adapters

Replaceable adapters should expose a small `CapabilityManifest` once they adopt the new capability contract. Manifests describe what an adapter can do without forcing orchestration code to branch on provider names.

Current capability vocabulary includes:

- search and record lookup
- outgoing references and incoming citations
- full text and supplements
- native metadata
- document metadata and document structure
- bibliography and inline citations
- figures, tables, and equations
- web, sitemap, feed, and link discovery

Manifests may also advertise supported media types and identifier schemes.

Conceptually:

```python
class CapabilityAwareAdapter(Protocol):
    @property
    def manifest(self) -> CapabilityManifest: ...
```

Application orchestration should prefer:

```python
adapters_supporting(adapters, Capability.REFERENCES_OUTBOUND)
```

over provider-name conditionals when the capability contract exists.

Existing adapters do not need a flag-day rewrite. New or materially upgraded adapters should adopt manifests first; older adapters can migrate when touched.

## Source observations

`SourceObservation` is a generic immutable envelope for source-native, reconstructed, or inferred information.

Use it to preserve:

- source/adapter identity and version
- provider-native record IDs
- media type
- bounded JSON-like native metadata
- an immutable artifact reference for raw/large payloads
- native vs reconstructed vs inferred basis
- observation time

Canonical typed fields remain canonical. Source observations are not a replacement for typed Work/Document/Evidence/Research models and must not become an everything-JSON persistence layer.

`WorkSourceRecord` remains the compatibility contract for the current scholarly discovery workflow. Migration should be incremental.

## Resource links

`ResourceLinkObservation` preserves an observed relationship to another URI before that target is acquired or resolved to canonical identity.

Examples include:

- canonical/alternate representation
- full text
- supplement
- dataset
- software
- citation
- version
- correction/retraction
- other related resource

Observing a URI does not imply Tarkka has acquired it, verified its identity, or decided retrieval is permitted.

## Plugin classes

### DiscoveryProvider

Searches a source of research metadata.

Required behaviors:

- provider identity/version
- normalized search
- pagination/checkpointing
- rate-limit behavior
- stable provider record IDs when available
- preservation of source-native metadata when the generic observation contract is adopted

Conceptual protocol:

```python
class DiscoveryProvider(Protocol):
    def search(self, query: ResearchQuery) -> DiscoveryPage: ...
```

Discovery capabilities may include search, record lookup, references, citations, native metadata, full-text links, or supplements. Do not assume every discovery provider supports every capability.

### ArtifactAcquirer

Acquires bytes or structured source material when permitted. The current generic boundary is
provider-neutral and stream-based:

```python
class ArtifactAcquirer(Protocol):
    @property
    def manifest(self) -> CapabilityManifest: ...

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision: ...

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact: ...
```

`assess()` is side-effect-free and distinguishes supported candidates from unsupported,
policy/rights-denied, and technically unavailable candidates. Runtime acquisition failures also
distinguish explicitly transient/retryable failures from terminal classes.

`acquire()` streams into a caller-owned binary sink instead of returning an entire payload in
memory. The returned `AcquiredArtifact` is a receipt containing requested/final URI, exact byte
count, SHA-256, optional media/filename hints, redirect provenance, and bounded metadata. It does
not create canonical `Artifact` identity; the application must independently commit and verify the
staged bytes first.

Acquisition adapters should preserve source-native metadata through `SourceObservation` rather
than expanding routing metadata into an unbounded JSON catch-all. See
[`ACQUISITION_CONTRACT.md`](ACQUISITION_CONTRACT.md) for the complete contract and failure model.

### Web/CrawlDiscovery adapter

Discovers web resources without embedding research identity or parser semantics in crawler code.

Conceptual flow:

```text
URL discovery
  -> HTTP observation
  -> content identification
  -> resource-link discovery
  -> media/format routing
```

Crawler traversal must be bounded by explicit depth/resource/request/byte/domain policies and should be resumable/checkpointed for substantial crawls.

### DocumentParser

Transforms an artifact into the canonical document representation while preserving the richest available native structure.

```python
class DocumentParser(Protocol):
    def supports(self, artifact: ArtifactManifest) -> SupportScore: ...
    async def parse(self, artifact: ArtifactRef) -> ParsedDocument: ...
```

Parsers should advertise format/structure capabilities when adopted. Examples:

- JATS/XML: metadata, bibliography, inline citations, figures, tables, equations, supplements
- EPUB: package metadata, reading order, navigation, XHTML/SVG resources
- semantic HTML: headings, links, figures/tables, structured metadata
- PDF/Docling: reconstructed layout, figures/tables/equations where supported
- scanned sources: optional OCR/layout/vision adapters

Do not flatten a richer native representation merely to route everything through Markdown.

### MetadataEnricher

Adds source-attributed metadata observations to canonical entities. Enrichers should preserve the native provider observation separately from the promoted canonical fields.

### Extractor

Runs a versioned extraction contract over a bounded source representation.

```python
class Extractor(Protocol):
    async def extract(self, request: ExtractionRequest) -> ExtractionResult: ...
```

The request identifies source objects, schema/contract, domain pack, and execution policy.

Extractors that infer meaning must produce inferred records/provenance; they must not rewrite native/reconstructed observations as though the inference were source-native fact.

### Verifier

Evaluates claim/evidence or citation relationships.

### Embedder

Generates vector representations. Embedding models remain infrastructure choices, not canonical data semantics.

### Reranker

Reorders candidates for a specific query.

### StorageBackend

Abstract only where useful. PostgreSQL remains the reference relational implementation; do not create lowest-common-denominator persistence abstractions that hide important database capabilities.

### ArtifactStore

Supports content-addressed put/get/stat and optional signed/authorized access.

### Exporter

Produces reports or interoperable data formats.

## Capability manifests

Plugins expose small manifests so agents and orchestration can discover capabilities without loading implementation documentation.

Example:

```yaml
name: jats
kind: parser
version: 1.0.0
supports:
  document_metadata: true
  document_structure: true
  bibliography: true
  inline_citations: true
  figures: true
  tables: true
  equations: true
  supplements: true
media_types:
  - application/xml
```

A discovery-provider example may advertise `search`, `record_lookup`, `references_outbound`, or `citations_inbound` independently.

## Provider/source inventory before implementation

Before adding or materially changing an adapter, audit the upstream source and record:

1. stable identifiers
2. native metadata fields
3. outgoing references/incoming citations
4. full-text/alternate/supplement/dataset/software links
5. author/organization/funder/award/license metadata
6. versions/corrections/retractions/relations
7. pagination/cursors/rate/update/deletion behavior
8. which fields are source-native versus provider inference
9. rights/access/retrieval/storage/redistribution constraints

Representative native provider payloads should become deterministic fixtures so future adapter changes cannot silently drop information.

## Configuration

Configuration should be layered:

1. package defaults
2. project/workspace config
3. environment variables/secrets references
4. runtime/CLI overrides

Secrets never belong in committed research manifests.

## Registration

Prefer explicit entry-point/plugin registration over filesystem magic.

A future implementation may use package entry points such as:

```text
tarkka.discovery
tarkka.parsers
tarkka.extractors
tarkka.exporters
tarkka.domain_packs
```

Do not add a heavyweight registry until multiple real adapters exercise the capability contract.

## Versioning

Plugins expose semantic versions and contract compatibility.

The core should be able to refuse incompatible plugins with a clear error before a long-running job begins.

## Determinism and caching

Plugins must identify all configuration that materially changes output so stage cache keys remain valid.

## Observability

Every plugin invocation should eventually provide standardized timing, outcome, retry, and resource-usage events.

## Security boundaries

Plugins are code and may have network/filesystem access. Institutional deployments should eventually support:

- allowlists
- sandboxed workers where practical
- explicit network permissions
- credential scopes
- signed/approved plugins
- dependency/SBOM scanning

Do not treat a community plugin as trusted merely because it follows the interface.

## Domain packs

Domain packs are a separate extension category. They primarily provide semantic configuration rather than network/infrastructure behavior.

A domain pack may contain:

```text
domain.yaml
ontology/
sources/
extraction/
quality/
skills/
reports/
mappings/
```

A domain pack can depend on plugin capabilities, but core plugins should not depend on one domain pack.

## Plugin quality requirements

Reference plugins should include as appropriate:

- contract tests
- preservation fixtures
- pagination tests
- retry/rate-limit tests
- normalization tests
- provenance tests
- deterministic cache-key tests
- capability-manifest tests
- malformed/native-payload tests
- graceful behavior for missing credentials or unavailable optional dependencies

Success means more than "the parser/provider returned something": tests should catch silent loss of previously preserved identifiers, relationships, bibliography, document structure, or native metadata.
