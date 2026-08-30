# Tarkka Proof Bundles

Tarkka proof bundles are portable, versioned evidence packages for independently inspecting preserved research state. The format is designed around one principle:

> A third party should be able to verify preserved source identity and exported lineage without trusting the machine, provider, model, or database that produced the bundle.

Proof bundles are export/read models. They do **not** create new canonical Work, Artifact, Document, Claim, Evidence, observation, citation, or verification identities.

## Versions

Bundle format: `tarkka-proof-bundle`

Recommended extension: `.tarkka`

Tarkka currently supports three explicit schema versions:

- **v1** — preserved source/document provenance;
- **v2** — v1 provenance plus canonical persisted Claim research state;
- **v3** — v2 plus integrity-bound deterministic normalized-Document content for replay.

Version 1 remains the CLI default for compatibility. Existing v1 and v2 bytes and verification semantics are frozen; newer versions are explicit opt-ins at creation time.

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

Create a v3 replay-ready bundle:

```bash
tarkka bundle create <document-id> \
  --schema-version 3 \
  --output research.tarkka
```

Creation honors the same `TARKKA_DOCUMENT_BACKEND` selection as Tarkka's document interfaces.

For PostgreSQL:

```bash
TARKKA_DOCUMENT_BACKEND=postgres \
TARKKA_DATABASE_URL=postgresql://user:password@host/database \
tarkka bundle create <document-id> \
  --schema-version 3 \
  --output research.tarkka
```

Creation performs no discovery, network, provider, or model calls. Tarkka exports only persisted state. Before publication, it re-hashes the preserved Artifact bytes and refuses to create a bundle when either the digest or byte count differs from the immutable Artifact record.

Publication is fail-closed: Tarkka writes a sibling temporary archive, flushes it, verifies that exact file offline, atomically replaces the destination, and flushes the destination directory on POSIX. A failed write or verification cannot publish an unverified archive or truncate a previous valid export.

## Coherent snapshots

A bundle must describe one coherent persistence snapshot rather than records observed at different write boundaries.

For local JSON, v1 locks the document/source catalogs together. V2 and v3 acquire the canonical document, source-observation, extraction, verification, and citation catalog paths before deciding which optional catalogs exist. Existing catalogs are opened and read only while the complete lock set is held. Missing optional research catalogs are treated as absent state where semantically valid; export does not create them as a side effect.

For PostgreSQL, all bundle versions use a read-only consistent transaction where their exported state requires multiple reads. V2 and v3 read source provenance, Claims, ExtractionRuns, Evidence, verification relations, cross-document Evidence source lineage, and Claim-document-local CitationContexts through one `REPEATABLE READ READ ONLY` transaction. Transaction-scoped caches avoid repeatedly loading the same persisted Document, Artifact, run, Evidence, Claim, or CitationContext during large exports.

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

### v3

A v3 archive contains exactly four members:

```text
manifest.json
artifacts/sha256/<64-character-lowercase-sha256>
research/claim-lineage.json
replay/normalized-document.json
```

All versions use stored, uncompressed ZIP members with fixed timestamps, canonical member order, Unix mode metadata, and no ZIP comments or extra metadata. Canonical JSON uses sorted keys, no insignificant whitespace, finite JSON numbers only, UTF-8 encoding, and one trailing newline. Identical canonical state therefore produces byte-identical bundle bytes.

## Research state in v2 and v3

`research/claim-lineage.json` is a canonical, versioned document research-state view. For every persisted Claim belonging to the bundled Document it preserves:

- the Claim identity, text, type, attribution, confidence, and review state;
- immutable ExtractionRun provenance;
- recorded model provider/name/version when a model was used;
- the Claim's original Evidence identities and exact source locators;
- source Document and immutable Artifact lineage for Evidence, including cross-document Evidence;
- persisted verification relations and verifier metadata;
- optional counter/supporting Evidence lineage;
- Claim-document-local CitationContext when a relation records one.

The manifest contains a `research_state` descriptor with the canonical member path, SHA-256 digest, and byte count. Bundle creation validates that the research-state Document identity agrees with the source Document before the member is encoded.

Model provenance is evidence about what produced the persisted result. Tarkka does **not** claim that a model call can be deterministically regenerated from that metadata.

## Deterministic normalized Document in v3

`replay/normalized-document.json` preserves the complete deterministic content of the normalized Document needed to compare a future parser replay against the frozen result. It includes:

- Document and Artifact identities;
- title;
- exact parser name and version;
- ordered sections and passages;
- passage text and exact character ranges;
- figures and their stable metadata;
- tables and their stable metadata;
- equations and their stable metadata.

`Document.normalized_at` is deliberately **not** part of deterministic replay content. It records when normalization happened and remains preserved in manifest provenance, but a correct replay performed later must not fail solely because its wall-clock timestamp differs.

The v3 manifest contains a `normalized_document` descriptor with the exact canonical path, SHA-256 digest, and byte count. Offline verification validates the complete normalized-Document JSON shape and domain-level structural invariants, then checks that its Document ID, Artifact ID, title, parser name, and parser version agree with the manifest.

V3 is replay-ready. Tarkka can verify the bundle, reconstruct the exact integrity-bound source Artifact in an isolated temporary workspace, resolve the exact recorded `(parser_name, parser_version)`, execute supported deterministic parsers offline, canonicalize the replayed normalized Document, and compare it against the frozen `replay/normalized-document.json` member. A different or unavailable parser version fails closed rather than silently substituting.

Current deterministic built-in replay identities are:

- `jats/1`;
- `latex/1`;
- `epub/1`;
- `semantic_html/1`;
- `plain-text/3`.

Historical `plain-text/2` is intentionally not treated as reproducible: it generated a random Document identity on each run. Replay therefore fails closed for that exact legacy identity rather than silently redefining its persisted semantics. Docling is classified as environment-sensitive and is not presented as deterministic replay unless its execution environment can be proven appropriately.

## Replay a v3 bundle offline

```bash
tarkka replay research.tarkka
```

Replay performs these steps locally:

1. fully verifies the v3 archive before parser execution;
2. rechecks the complete archive digest around replay-material reads and Artifact extraction;
3. reconstructs only the integrity-bound Artifact using a Tarkka-generated safe filename;
4. resolves only the exact persisted parser name and version;
5. executes the parser without following preserved source URIs or resource links;
6. canonicalizes the deterministic normalized-Document content;
7. compares the complete result with the frozen normalized-Document member;
8. emits a machine-readable result with implementation identity and bounded mismatch diagnostics.

Replay uses an isolated temporary workspace and removes it after execution. Hostile or traversing `original_name` values never become filesystem paths. Artifact materialization is checked against the manifest byte count and SHA-256 digest. Parser/support failures are translated to stable machine problems, and public source-derived diagnostic detail is bounded to avoid disclosure or output amplification while preserving the original chained exception internally.

CLI exit status is explicit:

- `0` — deterministic replay matched the frozen normalized Document;
- `1` — replay executed successfully but deterministic content differed;
- `2` — replay could not be executed safely or exactly, including invalid bundles, unavailable/legacy/environment-sensitive parsers, I/O failures, or integrity failures.

Replay proves deterministic normalized-Document equality for the executed parser boundary. It does **not** regenerate model-produced Claim/extraction state and does not claim stochastic provider/model execution is byte-for-byte reproducible.

## Replay a persisted Document through agent interfaces

Tarkka also exposes the same deterministic replay semantics without accepting a caller-supplied server filesystem path. The canonical transport-neutral operation is:

```text
research.documents.replay
```

It accepts one stable persisted `document_id`. The configured JSON or PostgreSQL backend creates a coherent v3 payload for that Document, Tarkka materializes a private ephemeral `.tarkka` archive, and the exact replay engine above verifies and executes it. The temporary archive and replay workspace are removed after the request.

MCP exposes:

```text
document_replay(document_id)
```

HTTP exposes the read-only, idempotent endpoint:

```text
GET /v1/documents/{document_id}/replay
```

The HTTP route accepts a UUID or `doc:<uuid>` handle and no query parameters. Blocking snapshot, archive, and parser work is executed off the ASGI event loop. MCP and HTTP both use the same transport-neutral replay result/error representation as the application service: deterministic status, expected/actual canonical digests, implementation identity, bounded mismatches, and stable bounded machine problems.

Neither agent transport accepts an arbitrary local bundle path, follows preserved source URIs/resource links, or performs discovery, provider, model, or network calls during deterministic replay. To replay an independently supplied archive by path, use the local CLI `tarkka replay <bundle.tarkka>` instead.

## Verify a bundle offline

```bash
tarkka bundle verify research.tarkka
```

Verification auto-dispatches by the explicit manifest schema version. It uses only the archive file and does not require a Tarkka home directory, database, network connection, API key, model, or provider.

The verifier fails closed on unknown schema versions, version/member mismatches, duplicate or unexpected members, noncanonical paths/ZIP metadata/JSON, invalid internal identities, size-limit violations, missing members, digest mismatches, malformed deterministic Document structure, and noncanonical added-member bytes.

Path-based verification is bounded and streaming. It validates archive metadata and declared member sizes before reading large payloads and hashes the embedded source Artifact incrementally.

Default limits are:

- archive: 1 GiB;
- manifest: 4 MiB;
- embedded source Artifact: 1 GiB;
- research state: 64 MiB;
- v3 normalized Document: 64 MiB.

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

Unknown or missing fields are rejected. V1 continues to mean exactly what it meant before later versions were introduced.

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

## Manifest v3

V3 reuses v2 and adds one required replay descriptor:

```json
{
  "artifact": {},
  "document": {},
  "format": "tarkka-proof-bundle",
  "normalized_document": {
    "path": "replay/normalized-document.json",
    "sha256": "<64-character-lowercase-sha256>",
    "size_bytes": 0
  },
  "research_state": {
    "path": "research/claim-lineage.json",
    "sha256": "<64-character-lowercase-sha256>",
    "size_bytes": 0
  },
  "resource_links": [],
  "schema_version": 3,
  "source_observations": [],
  "work_documents": []
}
```

Both integrity descriptors must match their canonical archive members exactly.

## Verification invariants

Verification is intentionally stricter than ordinary ZIP interoperability. Among other checks, Tarkka rejects bundles when:

1. the input is not a valid ZIP archive;
2. configured archive/member resource limits are exceeded;
3. an archive member is duplicated, missing, unexpected, or ordered incorrectly;
4. a member path is absolute, traversing, Windows-style, or otherwise noncanonical;
5. ZIP compression, timestamp, Unix mode, flags, comments, or extra metadata are noncanonical;
6. a manifest, research-state, or normalized-Document member is not valid canonical UTF-8 JSON;
7. object keys are duplicated or a number is non-finite;
8. the format/schema version is unsupported;
9. required fields are missing or unknown fields are present;
10. Artifact, Document, Work, observation, resource, research-state, or replay identities disagree;
11. the Artifact UUID does not match the identity derived from its SHA-256 digest;
12. the embedded Artifact byte length or streamed digest differs from the manifest;
13. a bundle omits or adds members contrary to its explicit schema version;
14. added-member bytes differ from their manifest descriptor digest or size;
15. added JSON members are not canonically encoded;
16. v3 normalized Document structure violates the deterministic replay contract.

## Determinism and replay

Bundle determinism means that the same canonical persisted snapshot produces the same archive bytes. It does not mean every process that originally produced that state is deterministic.

V3 makes the source → normalized Document step executable and content-verifiable for exact deterministic parser identities by preserving both the immutable input Artifact and the complete deterministic normalized output. Replay execution identity is reported separately from the equality predicate so Tarkka/Python/dependency metadata can be inspected without making timestamps or machine-local paths part of deterministic content.

Model-assisted steps remain transparent preserved observations. Future model-step replay records should preserve inputs, outputs, configuration, and model provenance without pretending stochastic provider execution can be regenerated byte-for-byte.

## Next extensions

The versioned bundle and exact-parser replay foundation makes the following extensions practical without changing the source/provenance model again:

1. optionally persist/sign replay attestations;
2. transparent model-step input/output/config records;
3. frozen/live research-state comparison with `tarkka diff`;
4. additional discovery/search/acquisition/policy provenance;
5. interoperability evaluation with PROV, JSON-LD, RO-Crate, and related standards after the native contract is stable.
