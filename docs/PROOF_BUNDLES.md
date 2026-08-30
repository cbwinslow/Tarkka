# Tarkka Proof Bundles

Tarkka proof bundles are portable, versioned evidence packages for independently inspecting preserved research state. The format is designed around one principle:

> A third party should be able to verify preserved source identity and exported lineage without trusting the machine, provider, model, or database that produced the bundle.

Proof bundles are export/read models. They do **not** create new canonical Work, Artifact, Document, Claim, Evidence, observation, citation, or verification identities.

## Versions

Bundle format: `tarkka-proof-bundle`

Recommended extension: `.tarkka`

Tarkka currently supports two explicit schema versions:

- **v1** — preserved source/document provenance;
- **v2** — v1 provenance plus canonical persisted Claim research state.

Version 1 remains the CLI default for compatibility. Existing v1 bytes and verification semantics are frozen; v2 is opt-in at creation time.

## Create a bundle

Create the compatibility-default v1 bundle:

```bash
tarkka bundle create <document-id> --output research.tarkka
```

The explicit equivalent is byte-identical:

```bash
tarkka bundle create <document-id> \
  --schema-version 1 \
  --output research.tarkka
```

Create a v2 research-state bundle:

```bash
tarkka bundle create <document-id> \
  --schema-version 2 \
  --output research.tarkka
```

Creation honors the same `TARKKA_DOCUMENT_BACKEND` selection as Tarkka's document interfaces.

For PostgreSQL:

```bash
TARKKA_DOCUMENT_BACKEND=postgres \
TARKKA_DATABASE_URL=postgresql://user:password@host/database \
tarkka bundle create <document-id> \
  --schema-version 2 \
  --output research.tarkka
```

Creation performs no discovery, network, provider, or model calls. Tarkka exports only persisted state. Before publication, it re-hashes the preserved Artifact bytes and refuses to create a bundle when either the digest or byte count differs from the immutable Artifact record.

Publication is fail-closed: Tarkka writes a sibling temporary archive, flushes it, verifies that exact file offline, atomically replaces the destination, and flushes the destination directory on POSIX. A failed write or verification cannot publish an unverified archive or truncate a previous valid export.

## Coherent snapshots

A bundle must describe one coherent persistence snapshot rather than records observed at different write boundaries.

For local JSON, v1 locks the document/source catalogs together. V2 extends the canonical lock set to every participating document, source-observation, extraction, verification, and citation catalog that exists. Missing optional research catalogs are treated as absent state where semantically valid; the export command does not create them as a side effect.

For PostgreSQL, both versions use one `REPEATABLE READ READ ONLY` transaction. V2 reads source provenance, Claims, ExtractionRuns, Evidence, verification relations, cross-document Evidence source lineage, and Claim-document-local CitationContexts through the same connection and transaction. Transaction-scoped caches avoid repeatedly loading the same persisted Document, Artifact, run, Evidence, Claim, or CitationContext during large exports.

## Archive layouts

### v1

A v1 archive contains exactly two members:

```text
manifest.json
artifacts/sha256/<64-character-lowercase-sha256>
```

### v2

A v2 archive contains exactly three members:

```text
manifest.json
artifacts/sha256/<64-character-lowercase-sha256>
research/claim-lineage.json
```

Both versions use stored, uncompressed ZIP members with fixed timestamps, canonical member order, Unix mode metadata, and no ZIP comments or extra metadata. Canonical JSON uses sorted keys, no insignificant whitespace, finite JSON numbers only, UTF-8 encoding, and one trailing newline. Identical canonical state therefore produces byte-identical bundle bytes.

## Research state in v2

`research/claim-lineage.json` is a canonical, versioned document research-state view. For every persisted Claim belonging to the bundled Document it preserves:

- the Claim identity, text, type, attribution, confidence, and review state;
- immutable ExtractionRun provenance;
- recorded model provider/name/version when a model was used;
- the Claim's original Evidence identities and exact source locators;
- source Document and immutable Artifact lineage for Evidence, including cross-document Evidence;
- persisted verification relations and verifier metadata;
- optional counter/supporting Evidence lineage;
- Claim-document-local CitationContext when a relation records one.

The v2 manifest contains a `research_state` descriptor with the canonical member path, SHA-256 digest, and byte count. Bundle creation validates that the research-state Document identity agrees with the source Document before the member is encoded.

Model provenance is evidence about what produced the persisted result. Tarkka does **not** claim that a model call can be deterministically regenerated from that metadata.

## Verify a bundle offline

```bash
tarkka bundle verify research.tarkka
```

Verification auto-dispatches by the explicit manifest schema version. It uses only the archive file and does not require a Tarkka home directory, database, network connection, API key, model, or provider.

The verifier fails closed on unknown schema versions, version/member mismatches, duplicate or unexpected members, noncanonical paths/ZIP metadata/JSON, invalid internal identities, size-limit violations, missing members, digest mismatches, and noncanonical v2 research-state bytes.

Path-based verification is bounded and streaming. It validates archive metadata and declared member sizes before reading large payloads and hashes the embedded source Artifact incrementally.

Default limits are:

- archive: 1 GiB;
- manifest: 4 MiB;
- embedded source Artifact: 1 GiB;
- v2 research state: 64 MiB.

Embedding applications can supply stricter verification limits.

A successful result includes:

- bundle SHA-256;
- normalized Document ID;
- source Artifact SHA-256;
- source Artifact byte count;
- archive member count.

## Manifest v1

The v1 top-level manifest fields are strict:

```json
{
  "artifact": {},
  "document": {},
  "format": "tarkka-proof-bundle",
  "resource_links": [],
  "schema_version": 1,
  "source_observations": [],
  "work_documents": []
}
```

Unknown or missing fields are rejected. V1 continues to mean exactly what it meant before v2 was introduced.

### Source fields

`artifact` records immutable source identity and the embedded content-addressed member path. Its `artifact_id` must equal Tarkka's canonical UUIDv5 derived from `urn:sha256:<sha256>`.

`document` records the parser-versioned normalized Document identity and must reference the bundled Artifact.

`work_documents` records canonical Work↔Document representation links available in the selected persistence backend.

`source_observations` preserves provider/native/reconstructed observation envelopes, including basis, source version, provider record identity, metadata, and observation time.

`resource_links` preserves source-observed links to supplements, datasets, software, alternate representations, corrections, retractions, and related resources. Bundle creation records these URIs but never resolves or fetches them.

## Manifest v2

V2 reuses the v1 source/document structures and adds one required descriptor:

```json
{
  "artifact": {},
  "document": {},
  "format": "tarkka-proof-bundle",
  "research_state": {
    "path": "research/claim-lineage.json",
    "sha256": "<64-character-lowercase-sha256>",
    "size_bytes": 0
  },
  "resource_links": [],
  "schema_version": 2,
  "source_observations": [],
  "work_documents": []
}
```

The descriptor digest and byte count must match the canonical research-state member exactly.

## Verification invariants

Verification is intentionally stricter than ordinary ZIP interoperability. Among other checks, Tarkka rejects bundles when:

1. the input is not a valid ZIP archive;
2. configured archive/member resource limits are exceeded;
3. an archive member is duplicated, missing, unexpected, or ordered incorrectly;
4. a member path is absolute, traversing, Windows-style, or otherwise noncanonical;
5. ZIP compression, timestamp, Unix mode, flags, comments, or extra metadata are noncanonical;
6. a manifest or research-state member is not valid canonical UTF-8 JSON;
7. object keys are duplicated or a number is non-finite;
8. the format/schema version is unsupported;
9. required fields are missing or unknown fields are present;
10. Artifact, Document, Work, observation, resource, or research-state identities disagree;
11. the Artifact UUID does not match the identity derived from its SHA-256 digest;
12. the embedded Artifact byte length or streamed digest differs from the manifest;
13. a v2 bundle omits or adds the research-state member contrary to its schema version;
14. v2 research-state bytes differ from the manifest descriptor digest or size;
15. v2 research-state JSON is not canonically encoded.

## Determinism and replay

Bundle determinism means that the same canonical persisted snapshot produces the same archive bytes. It does not mean every process that originally produced that state is deterministic.

Non-model transformation replay and transparent model-step records are separate concerns. Future replay work should preserve inputs, outputs, configuration, and model provenance without pretending stochastic provider execution can be regenerated byte-for-byte.

## Next extensions

The v2 foundation makes the following extensions practical without changing the source/provenance model again:

1. deterministic replay of non-model transformations;
2. transparent model-step input/output/config records;
3. frozen/live research-state comparison with `tarkka diff`;
4. additional discovery/search/acquisition/policy provenance;
5. interoperability evaluation with PROV, JSON-LD, RO-Crate, and related standards after the native contract is stable.
