# Tarkka Proof Bundles

Tarkka proof bundles are portable, versioned evidence packages for independently inspecting preserved research state. The format is designed around one principle:

> A third party should be able to verify preserved source identity and exported lineage without trusting the machine, provider, model, or database that produced the bundle.

Proof bundles are export/read models. They do **not** create new canonical Work, Artifact, Document, observation, or relation identities.

## Current format

Bundle format: `tarkka-proof-bundle`

Schema version: `1`

File extension: `.tarkka` is recommended but not required.

A v1 bundle is a deterministic ZIP archive with exactly two members:

```text
manifest.json
artifacts/sha256/<64-character-lowercase-sha256>
```

The archive uses stored, uncompressed ZIP members with fixed metadata. Member ordering and manifest serialization are canonical, so the same persisted Tarkka state produces byte-identical bundle bytes.

## Create a bundle

```bash
tarkka bundle create <document-id> --output research.tarkka
```

Creation reads Tarkka's existing local research catalog, artifact store, Work↔Document links, source observations, and source-observed resource links. It does not call a discovery provider, model, or network service.

Before exporting, Tarkka re-hashes the preserved artifact bytes and refuses to create the bundle if either the SHA-256 digest or byte count differs from the immutable Artifact record.

The command writes the bundle and immediately verifies the resulting file before reporting success.

## Verify a bundle offline

```bash
tarkka bundle verify research.tarkka
```

Verification uses only the archive bytes. It does not require a Tarkka home directory, database, network connection, API key, model, or provider.

A successful result includes:

- bundle SHA-256;
- normalized Document ID;
- source Artifact SHA-256;
- source Artifact byte count;
- archive member count.

## Manifest v1

`manifest.json` is UTF-8 JSON serialized with sorted keys, no insignificant whitespace, and one trailing newline.

Top-level fields are strict and versioned:

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

Unknown or missing fields are rejected in v1. Future format evolution must use an explicit schema version rather than silently changing the meaning of existing fields.

### `artifact`

Records the immutable source Artifact identity and embedded member location:

- `artifact_id`
- `sha256`
- `size_bytes`
- `media_type`
- `path`
- `original_name`
- `source_uri`
- `acquired_at`

`path` must be exactly `artifacts/sha256/<sha256>`.

### `document`

Records the parser-versioned normalized Document identity:

- `document_id`
- `artifact_id`
- `title`
- `parser_name`
- `parser_version`
- `normalized_at`

The Document's `artifact_id` must equal the bundled Artifact identity.

### `work_documents`

Records existing canonical Work↔Document representation links:

- `link_id`
- `work_id`
- `artifact_id`
- `document_id`
- `linked_at`

Every exported link must reference the bundled Artifact and Document.

### `source_observations`

Preserves the observation envelope used for provider/native/reconstructed metadata:

- `observation_id`
- `source_name`
- `basis`
- `source_version`
- `provider_record_id`
- `media_type`
- `native_artifact_id`
- `metadata`
- `observed_at`

Metadata remains JSON-compatible source data. The bundle does not promote it into new canonical fields.

### `resource_links`

Preserves source-observed links to supplements, datasets, software, alternate representations, corrections, retractions, and related resources:

- `link_id`
- `observation_id`
- `target_uri`
- `relation`
- `media_type`
- `label`
- `metadata`

Every resource link must reference a source observation included in the same manifest. Targets remain observed URIs; bundle creation does not resolve or fetch them.

## Verification rules

The v1 verifier fails closed when any of these checks fail:

1. the input is not a valid ZIP archive;
2. any archive member is duplicated;
3. a member path is absolute, contains traversal components, Windows separators/drives, or other noncanonical path structure;
4. `manifest.json` is missing;
5. the manifest is not valid UTF-8 JSON;
6. JSON object keys are duplicated;
7. the bundle format/schema version is unsupported;
8. required fields are missing or unknown fields are present;
9. internal Artifact/Document/Work/observation/resource identities are inconsistent;
10. the archive has missing or unexpected members;
11. embedded artifact byte length differs from the manifest;
12. embedded artifact SHA-256 differs from the manifest;
13. the manifest is not canonically encoded;
14. the ZIP bytes are not the canonical deterministic encoding of the verified payload.

Verification is intentionally stricter than ordinary ZIP interoperability. Canonical encoding makes the whole bundle content-addressable and gives downstream systems a stable byte-level identity.

## Determinism and model-assisted research

Bundle v1 exports only deterministic preserved source/document lineage. It does not yet include claims, evidence relations, citations, discovery snapshots, policy decisions, or model invocations.

Those records will be added as explicitly versioned sections. When model-assisted state is exported, Tarkka will preserve provider/model/prompt/version metadata and the resulting observation rather than pretending a model call can be deterministically replayed.

## Planned v1 extensions

Priority A under the product roadmap will build on this foundation with:

1. claim/evidence/verification and exact citation-span sections;
2. discovery/search/acquisition/policy provenance;
3. deterministic replay of non-model transformations;
4. compact lineage inspection (`why`) and MCP/API bundle verification;
5. frozen/live research-state diffing;
6. interoperability evaluation with established provenance/research packaging standards before any mapping is standardized.

The archive codec and manifest contract are intentionally independent of Tarkka's JSON persistence adapter so other storage backends and third-party tools can emit or consume compatible bundles later.
