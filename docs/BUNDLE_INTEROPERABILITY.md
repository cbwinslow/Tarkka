# Bundle interoperability: RO-Crate export design note

This resolves the five open questions in issue #376 (issue #198 Priority F) before any code was
written, per this repository's spec-driven-change-contract. It covers v1-equivalent scope only
(Artifact + Document). Claim/Evidence/citation lineage and any use of PROV-O are explicitly
deferred to a separate follow-up issue, per #376's non-goals.

This is an **additive, read/export-only** representation. It does not replace, weaken, or change
the native `.tarkka` v1/v2/v3 bundle format, `tarkka bundle verify`, or `tarkka replay`. See
[`PROOF_BUNDLES.md`](PROOF_BUNDLES.md) for that contract.

## 1. RO-Crate spec version

**Decision: target RO-Crate 1.2, `conformsTo` = `https://w3id.org/ro/crate/1.2`.**

Verified directly against the published specification: RO-Crate 1.2's status page states
"Status: Recommendation" (published 2025-06-04) — RO-Crate's own term for a stable, finalized
release. A newer 1.3 exists (a Zenodo-deposited "RO-Crate Metadata Specification 1.3.0" record was
found), but this review did not confirm 1.3 has reached the same Recommendation status as 1.2, so
1.2 is the safer current target.

**Version-currency plan:** the target version is a single named constant
(`RO_CRATE_SPEC_VERSION` in the implementation), not inferred or auto-updated. Bumping it requires:
confirming the new version's status is Recommendation (or equivalent stable status), updating the
constant and the emitted `conformsTo` value, and re-running the independent-tool validation (see
§3) against the new version before merging. This is a manual, deliberate upgrade, matching how this
repository already pins the native bundle's `PROOF_BUNDLE_SCHEMA_VERSION`.

Sources: [RO-Crate 1.2 specification](https://www.researchobject.org/ro-crate/specification/1.2/index.html), [RO-Crate 1.2 release announcement](https://esciencelab.org.uk/ro-crate/announcements/2025/06/04/ro-crate-1.2-released/), [RO-Crate Metadata Specification 1.3.0 (Zenodo)](https://zenodo.org/records/20720080).

## 2. Content hash as a JSON-LD property

**Decision: `schema:sha256` (used unprefixed as `sha256`, which RO-Crate's context resolves to
schema.org), not SPDX, not a Tarkka-defined term.**

Verified directly against the schema.org vocabulary: `sha256`'s definition is "The SHA-2 SHA256
hash of the content of the item," its value type is `Text`, and its domain is `MediaObject`.
RO-Crate's `File` entity is explicitly defined as an RO-Crate alias for schema.org's `MediaObject`,
so `schema:sha256` is domain-correct for exactly the entity representing our immutable Artifact. A
web search additionally found this property already in active use for exactly this purpose: RO-Crate
profiles use `sha256` to describe container image checksums, and Google's Croissant dataset format
(schema.org/RO-Crate-adjacent) uses `sha256` on its `FileObject` entities the same way. SPDX's
`checksum`/`Checksum` node type is a real, more general-purpose alternative, but it requires pulling
in a second vocabulary and a nested node for something schema.org already expresses directly with
one scalar property — unnecessary complexity for a single SHA-256 digest.

Sources: [schema.org/sha256](https://schema.org/sha256) (definition, domain, value type verified directly), web search results confirming RO-Crate container-image and Croissant `FileObject` usage.

**Resolved during implementation:** an automated fetch of RO-Crate's raw JSON-LD context document
was inconclusive about whether `sha256` resolves without extra declaration, so this was flagged as
open above pending real validation. That validation has since happened: loading an emitted crate
with the `rocrate` library (see §3) parses the `File` entity's `sha256` property correctly, with
the literal hex digest intact, confirming `schema:sha256` round-trips through RO-Crate's context
exactly as expected. The same load also confirmed every inline Tarkka-specific term (`documentId`,
`parserName`, `parserVersion`, `normalizedAt`, `TarkkaNormalizedDocument`) resolves correctly from
the embedded inline `@context` object. `tests/test_ro_crate_export.py` keeps this real going
forward, not just verified once by hand.

## 3. Independent validation tooling

**Decision: `rocrate` (PyPI package name; GitHub repo `ResearchObject/ro-crate-py`), added as a
dev-only test dependency.**

Verified: Apache-2.0 licensed (compatible with Tarkka's own Apache-2.0 license — see `AGENTS.md`'s
dependency rule), latest release 0.15.1 as of July 2026, maintained by the RO-Crate specification's
own steward institutions (University of Manchester, VIB, Barcelona Supercomputing Center, CRS4,
EPFL) — i.e., this is not a third-party reimplementation but tooling from the standard's own
authors. It provides `ROCrate(path)` to load and parse an existing crate directory or
`ro-crate-metadata.json`, and `get_entities()`/`dereference()` to inspect parsed entities. This
review confirmed those APIs exist from the library's own documentation but did not execute the
library directly before writing this note; the implementation step exercises it for real as part
of the test suite, which is the actual proof this acceptance criterion requires.

It is a test-only dependency: added to `[dependency-groups] dev`, never imported from
`src/tarkka` runtime code.

Source: [ResearchObject/ro-crate-py](https://github.com/ResearchObject/ro-crate-py), PyPI `rocrate` package search results.

## 4. Tarkka-specific JSON-LD context terms

**Decision for v1: an inline `@context` object embedded directly in each emitted
`ro-crate-metadata.json`, not a term resolved from an externally hosted URL.**

Neither schema.org nor RO-Crate define terms for `document_id`, `parser_name`, `parser_version`, or
a distinct "normalized document" type — these are genuinely Tarkka-specific and the issue
anticipated minting context terms for exactly this case. However, this repository has no stable,
versioned public URL to host a resolvable JSON-LD context document at (unlike schema.org or
w3id.org, which are long-lived registered namespaces). Publishing an `@context` entry that points
at a URL which could 404 or move (e.g., a branch-relative GitHub raw URL) would be **worse** than
not resolving it at all: a compliant JSON-LD processor that tries to dereference a broken context
URL fails harder than one that finds all its terms already inline.

JSON-LD's `@context` value may be an array mixing a remote context URL and an inline context
object — this is standard, not a workaround. The implementation therefore uses:

```json
"@context": [
  "https://w3id.org/ro/crate/1.2/context",
  {
    "tarkka": "https://github.com/cbwinslow/Tarkka/blob/main/docs/BUNDLE_INTEROPERABILITY.md#tarkka-context-v1",
    "TarkkaNormalizedDocument": "tarkka:TarkkaNormalizedDocument",
    "documentId": "tarkka:documentId",
    "parserName": "tarkka:parserName",
    "parserVersion": "tarkka:parserVersion",
    "normalizedAt": "tarkka:normalizedAt"
  }
]
```

The `tarkka:` prefix IRI above points at this design note's own section, not a machine-readable
context document — it is a human-readable anchor, not a dereferenceable JSON-LD context. This is an
explicit, acknowledged limitation, not a silently-glossed-over gap: **publishing a real, versioned,
machine-resolvable Tarkka JSON-LD context at a stable hosted URL (e.g., once the project has a
durable domain or GitHub Pages target) is an open follow-up**, not resolved by this change. Anyone
consuming these Tarkka-specific terms today must do so by reading the inline context object
directly (which every JSON-LD processor already does correctly), not by dereferencing `tarkka:`.

### Tarkka context v1

| Term | Maps to | Applies to |
| --- | --- | --- |
| `TarkkaNormalizedDocument` | `tarkka:TarkkaNormalizedDocument` | Additional `@type` alongside `CreativeWork` for the Document entity |
| `documentId` | `tarkka:documentId` | Document entity — Tarkka's canonical Document UUID |
| `parserName` | `tarkka:parserName` | Document entity — exact deterministic parser identity, see `PROOF_BUNDLES.md` |
| `parserVersion` | `tarkka:parserVersion` | Document entity — exact deterministic parser version |
| `normalizedAt` | `tarkka:normalizedAt` | Document entity — when normalization happened (not part of any replay-determinism claim, matching the native bundle's own treatment of this field) |

## 5. PROV-O in the JSON-LD context

**Decision for v1: do not embed PROV-O at all yet.** V1 scope has exactly one derivation
relationship — Document derived from Artifact — which schema.org already expresses natively via
`isBasedOn` ("A resource from which this work is derived"). Introducing a second vocabulary for one
edge that schema.org already covers would be unjustified complexity for this scope.

This review did find precedent that extending an RO-Crate context with external vocabularies is
idiomatic: RO-Crate's own context document incorporates terms from Bioschemas and CodeMeta
alongside schema.org. So embedding PROV-O terms later, when the v2-equivalent follow-up adds actual
Claim/Evidence/verification lineage (multiple typed Activities and Entities, not one static
derivation edge), is architecturally sound and not a new pattern for RO-Crate — it is simply not
needed yet for this scope.

## 6. Model-assisted extraction provenance

**Explicitly out of scope for this change.** V1 exports Artifact and Document only; there is no
Claim in scope, and therefore no model-assisted extraction provenance to represent at all. Whether
to express it as a PROV `Agent`/`Activity` pair, and how to avoid implying deterministic
reproducibility of a stochastic model step (the native bundle format's own `PROOF_BUNDLES.md`
already states model provenance is "evidence about what produced the persisted result," not a
reproducibility claim) is left as an explicit open question for the v2-equivalent follow-up issue,
where it can be answered with the real Claim/Evidence field shapes in view instead of speculatively
now.

## Example emitted crate

This is a real `ro-crate-metadata.json` produced end to end by `tarkka ingest` →
`tarkka bundle create` → `tarkka bundle export-ro-crate` against the JATS fixture used in this
repository's own tests (`tests/fixtures/jats/sample_article.xml`), loaded successfully by the
independent `rocrate` library. The `url` value below is shortened to a portable example path; the
literal output otherwise carries the real digests, IDs, and timestamps that command produced.

```json
{
  "@context": [
    "https://w3id.org/ro/crate/1.2/context",
    {
      "tarkka": "https://github.com/cbwinslow/Tarkka/blob/main/docs/BUNDLE_INTEROPERABILITY.md#tarkka-context-v1",
      "TarkkaNormalizedDocument": "tarkka:TarkkaNormalizedDocument",
      "documentId": "tarkka:documentId",
      "parserName": "tarkka:parserName",
      "parserVersion": "tarkka:parserVersion",
      "normalizedAt": "tarkka:normalizedAt"
    }
  ],
  "@graph": [
    {
      "@id": "ro-crate-metadata.json",
      "@type": "CreativeWork",
      "conformsTo": { "@id": "https://w3id.org/ro/crate/1.2" },
      "about": { "@id": "./" }
    },
    {
      "@id": "./",
      "@type": "Dataset",
      "conformsTo": { "@id": "https://w3id.org/ro/crate/1.2" },
      "hasPart": [
        { "@id": "files/f64b10c46ccf25b3e3a0020ca9f7a1825d3f25cad49ec6719bd1c6998907be2c" }
      ],
      "mainEntity": { "@id": "#document-85e9747c-93ee-564a-ac49-b68bb076cd58" }
    },
    {
      "@id": "files/f64b10c46ccf25b3e3a0020ca9f7a1825d3f25cad49ec6719bd1c6998907be2c",
      "@type": "File",
      "sha256": "f64b10c46ccf25b3e3a0020ca9f7a1825d3f25cad49ec6719bd1c6998907be2c",
      "contentSize": "2155",
      "encodingFormat": "application/xml",
      "name": "sample_article.xml",
      "url": "file:///example/tests/fixtures/jats/sample_article.xml"
    },
    {
      "@id": "#document-85e9747c-93ee-564a-ac49-b68bb076cd58",
      "@type": ["CreativeWork", "TarkkaNormalizedDocument"],
      "name": "Native Structure Fixture",
      "isBasedOn": {
        "@id": "files/f64b10c46ccf25b3e3a0020ca9f7a1825d3f25cad49ec6719bd1c6998907be2c"
      },
      "documentId": "85e9747c-93ee-564a-ac49-b68bb076cd58",
      "parserName": "jats",
      "parserVersion": "1",
      "normalizedAt": "2026-09-13T10:07:36.942514+00:00"
    }
  ]
}
```

## Summary of decisions

| Question | Decision | Confidence |
| --- | --- | --- |
| RO-Crate version | 1.2 (`conformsTo: https://w3id.org/ro/crate/1.2`) | Verified (status page fetched directly) |
| Content hash property | `sha256` (schema.org, via RO-Crate's context) | Fully verified: definition/domain confirmed directly, context resolution confirmed by loading a real emitted crate with `rocrate` |
| Tarkka-specific terms | Inline `@context` object; no hosted context URL yet | Deliberate, explicitly incomplete — follow-up needed |
| PROV-O | Deferred to v2-equivalent follow-up | Not attempted for v1 (no lineage edges beyond one `isBasedOn`) |
| Model provenance | Deferred to v2-equivalent follow-up | Not attempted (no Claim in v1 scope) |
