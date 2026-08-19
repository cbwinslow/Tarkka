# Connector and Plugin Specification

## Purpose

The platform should gain capabilities through narrow interfaces rather than accumulating source-specific logic throughout the codebase.

## Plugin classes

### DiscoveryProvider

Searches a source of research metadata.

Required capabilities:

- provider identity/version
- capability manifest
- normalized search
- pagination/checkpointing
- rate-limit metadata
- stable provider record IDs when available

Conceptual protocol:

```python
class DiscoveryProvider(Protocol):
    async def capabilities(self) -> ProviderCapabilities: ...
    async def search(self, query: ResearchQuery, cursor: str | None = None) -> SearchPage: ...
```

### ArtifactAcquirer

Acquires bytes or structured source material when permitted.

```python
class ArtifactAcquirer(Protocol):
    async def can_acquire(self, candidate: ArtifactCandidate) -> AcquisitionDecision: ...
    async def acquire(self, candidate: ArtifactCandidate) -> AcquiredArtifact: ...
```

The acquisition decision must distinguish technical unavailability from policy/rights denial.

### DocumentParser

Transforms an artifact into the canonical document representation.

```python
class DocumentParser(Protocol):
    def supports(self, artifact: ArtifactManifest) -> SupportScore: ...
    async def parse(self, artifact: ArtifactRef) -> ParsedDocument: ...
```

### MetadataEnricher

Adds source-attributed metadata observations to canonical entities.

### Extractor

Runs a versioned extraction contract over a bounded source representation.

```python
class Extractor(Protocol):
    async def extract(self, request: ExtractionRequest) -> ExtractionResult: ...
```

The request identifies source objects, schema/contract, domain pack, and execution policy.

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
name: openalex
kind: discovery_provider
version: 1.0.0
supports:
  search: true
  citation_graph: true
  concepts: true
  full_text: false
limits:
  max_page_size: 100
credentials:
  required: false
```

## Configuration

Configuration should be layered:

1. package defaults
2. project/workspace config
3. environment variables/secrets references
4. runtime/CLI overrides

Secrets never belong in committed research manifests.

## Registration

Prefer explicit entry-point/plugin registration over filesystem magic.

A future Python implementation may use package entry points such as:

```text
research_platform.discovery
research_platform.parsers
research_platform.extractors
research_platform.exporters
research_platform.domain_packs
```

The exact namespace should follow the final project name.

## Versioning

Plugins expose semantic versions and contract compatibility.

The core should be able to refuse incompatible plugins with a clear error before a long-running job begins.

## Determinism and caching

Plugins must identify all configuration that materially changes output so stage cache keys remain valid.

## Observability

Every plugin invocation should provide standardized timing, outcome, retry, and resource-usage events.

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

Reference plugins should include:

- contract tests
- fixtures
- pagination tests
- retry/rate-limit tests
- normalization tests
- provenance tests
- deterministic cache-key tests
- graceful behavior for missing credentials or unavailable optional dependencies
