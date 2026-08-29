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

The archive uses stored, uncompressed ZIP members with fixed timestamps, Unix mode metadata, member order, and no ZIP comments or extra metadata. Manifest serialization is canonical, so identical persisted research state produces byte-identical bundle bytes.

## Create a bundle

```bash
tarkka bundle create <document-id> --output research.tarkka
```

Creation honors the same `TARKKA_DOCUMENT_BACKEND` selection as Tarkka's document interfaces.

For the local JSON backend, Tarkka acquires the research-catalog and source-observation locks together in canonical path order and reads all exported state while both locks are held. This prevents an export from combining records observed at different write boundaries.

For the PostgreSQL backend, Tarkka reads the Document, Artifact, source observations, and resource links through one `REPEATABLE READ READ ONLY` transaction. PostgreSQL v1 bundles intentionally omit Work↔Document links because that representation-link relation is not yet persisted in the PostgreSQL schema; Tarkka does **not** mix potentially stale JSON representation links into a PostgreSQL export.

Creation does not call a discovery provider, model, or network service. Before exporting, Tarkka re-hashes the preserved artifact bytes and refuses to create the bundle if either the SHA-256 digest or byte count differs from the immutable Artifact record.

Publication is fail-closed. Tarkka writes a sibling temporary archive, flushes it to durable storage, verifies that exact file offline, then atomically replaces the destination and flushes the destination directory on POSIX. A failed write or verification therefore cannot publish an unverified archive or truncate a previous valid export. The create command reports the verification result produced during that publication step instead of re-reading the full bundle a second time.

## Verify a bundle offline

```bash
tarkka bundle verify research.tarkka
```

Verification uses only the archive file. It does not require a Tarkka home directory, database, network connection, API key, model, or provider.

Path-based verification is bounded and streaming. The verifier checks archive metadata and declared member sizes before reading member payloads, then hashes the source Artifact incrementally rather than loading the entire archive or Artifact into memory.

Default v1 limits are:

- archive: 1 GiB;
- manifest: 4 MiB;
- embedded source Artifact: 1 GiB.

The verification API accepts explicit limits so embedding applications can impose stricter resource budgets.

A successful result includes:

- bundle SHA-256;
- normalized Document ID;
- source Artifact SHA-256;
- source Artifact byte count;
- archive member count.

## Manifest v1

`manifest.json` is UTF-8 JSON serialized with sorted keys, no insignificant whitespace, finite JSON numbers only, and one trailing newline.

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

`path` must be exactly `artifacts/sha256/<sha256>`. The `artifact_id` must also equal Tarkka's canonical UUIDv5 derived from `urn:sha256:<sha256>`; a manifest cannot substitute an unrelated UUID while preserving the same source bytes.

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

Records canonical Work↔Document representation links available in the selected persistence backend:

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

`basis` is restricted to Tarkka's canonical `ObservationBasis` vocabulary (`native`, `reconstructed`, or `inferred`). Metadata is deeply validated as finite JSON-compatible data before export. Any non-null `native_artifact_id` must refer to the Artifact embedded in the same bundle; verification fails closed if a manifest claims observation provenance for another Artifact.

### `resource_links`

Preserves source-observed links to supplements, datasets, software, alternate representations, corrections, retractions, and related resources:

- `link_id`
- `observation_id`
- `target_uri`
- `relation`
- `media_type`
- `label`
- `metadata`

`relation` is restricted to Tarkka's canonical `ResourceRelation` vocabulary. Every resource link must reference a source observation included in the same manifest. Targets remain observed URIs; bundle creation does not resolve or fetch them.

## Verification rules

The v1 verifier fails closed when any of these checks fail:

1. the input is not a valid ZIP archive;
2. configured archive, manifest, or source-Artifact resource limits are exceeded;
3. any archive member is duplicated or an unexpected member is present;
4. a member path is absolute, contains traversal components, Windows separators/drives, or other noncanonical path structure;
5. ZIP compression, timestamp, Unix mode, flags, comments, extra metadata, order, or member layout is noncanonical;
6. `manifest.json` is missing;
7. the manifest is not valid UTF-8 JSON;
8. JSON object keys are duplicated or a number is non-finite;
9. the bundle format/schema version is unsupported;
10. required fields are missing or unknown fields are present;
11. the Artifact UUID does not match the canonical identity derived from its SHA-256 digest;
12. observation basis or resource relation contains a value outside Tarkka's canonical vocabulary;
13. internal Artifact/Document/Work/observation/resource identities are inconsistent;
14. a source observation claims a different native Artifact;
15. embedded Artifact byte length differs from the manifest or from the streamed byte count;
16. streamed embedded Artifact SHA-256 differs from the manifest;
17. the manifest is not canonically encoded.

Verification is intentionally stricter than ordinary ZIP interoperability. Canonical encoding makes the whole bundle content-addressable and gives downstream systems a stable byte-level identity.

## Determinism and model-assisted research

Bundle v1 exports only deterministic preserved source/document lineage. It does not yet include claims, evidence relations, citations, discovery snapshots, policy decisions, or model invocations.

Those records will be added as explicitly versioned sections. When model-assisted state is exported, Tarkka will preserve provider/model/prompt/version metadata and the resulting observation rather than pretending a model call can be deterministically replayed.

## Planned extensions

Priority A under the product roadmap will build on this foundation with:

1. claim/evidence/verification and exact citation-span sections;
2. discovery/search/acquisition/policy provenance;
3. deterministic replay of non-model transformations;
4. compact lineage inspection (`why`) and MCP/API bundle verification;
5. frozen/live research-state diffing;
6. PostgreSQL persistence for Work↔Document representation links;
7. interoperability evaluation with established provenance/research packaging standards before any mapping is standardized.

The archive codec and manifest contract are intentionally independent of Tarkka's persistence adapters so other storage backends and third-party tools can emit or consume compatible bundles later.
