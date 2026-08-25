# Security, Privacy, Licensing, and Research Rights

## Principle

A research platform may process sensitive, proprietary, licensed, embargoed, or copyrighted material. Security and rights cannot be bolted on after ingestion.

## Separate concerns

Do not collapse these questions into one `license` field:

1. May the user access the source?
2. May the platform fetch it automatically?
3. May the platform store a private copy?
4. May it transform/parse/index/embed the content?
5. May derived snippets be displayed?
6. May the full content be redistributed?
7. May it be used commercially?
8. Is attribution required?
9. Is access temporary, embargoed, or revocable?

Unknown must remain unknown.

## User-provided content

The platform should support private user-provided material without assuming redistribution rights.

Examples:

- institutional subscriptions
- licensed finance research
- internal corporate reports
- private research notes
- unpublished manuscripts

A self-hosted user may be allowed to process content that the public project cannot legally host or redistribute.

## Source policy

Each acquisition provider should have a source-policy descriptor covering:

- official API vs scraping
- robots behavior
- rate limits
- credential requirements
- permitted acquisition modes
- known rights metadata sources
- whether raw content may be retained

## Credentials

Requirements:

- never commit credentials to repository manifests
- environment/secret-manager references
- least privilege
- redact secrets from logs/traces/snapshots
- scoped credentials per provider when practical
- rotate/revoke support

## Network security

Acquisition and plugin infrastructure must defend against:

- SSRF
- malicious redirects
- oversized downloads
- decompression bombs
- unexpected MIME/content types
- local-network access from untrusted URLs
- credential leakage across origins

Institutional profiles should support network egress policy.

## Artifact security

User-supplied documents are untrusted inputs.

Requirements:

- hash before processing
- size/type limits
- parser isolation strategy for risky formats
- archive traversal protections
- no execution of embedded macros/scripts
- quarantine path for malformed/suspicious files

## Prompt injection / content injection

Research documents can contain text designed to manipulate AI systems.

Extractors and agents must treat document content as **data**, not instructions.

Controls should include:

- clear instruction/content boundaries
- structured extraction schemas
- least-capability tools during document analysis
- no tool execution based solely on document instructions
- provenance tagging of untrusted source content

## Plugin security

Community plugins execute code and therefore have a different trust level than domain configuration.

Future controls may include:

- plugin allowlists
- signatures/provenance
- lockfiles
- dependency scanning
- SBOM generation
- sandboxed workers
- filesystem/network capability restrictions

## Multi-tenancy

Institutional deployment requires strict workspace/organization boundaries.

Design toward:

- tenant-scoped authorization at application and database boundaries
- row-level security evaluation where appropriate
- scoped artifact URLs
- per-tenant keys/policies where required
- audit logs
- quota/resource isolation

Do not claim multi-tenant security until it is explicitly tested.

## Privacy

Allow local/self-hosted processing paths for users who cannot send research content to external models.

Model-provider adapters should expose data-handling metadata so policy can route sensitive work to approved/local providers.

## Logging and telemetry

Logs must not casually contain:

- full document text
- API keys
- private URLs with tokens
- sensitive extracted data

Prefer IDs/hashes and structured event metadata.

Telemetry should be opt-in or transparently configurable for the open-source self-hosted distribution.

## Software license

Tarkka's software is licensed under Apache-2.0. This permissive license supports institutional
and commercial adoption while providing an express patent grant. It applies only to Tarkka's
software and project-authored documentation, not to ingested research content or external data.

When adding a dependency, fixture, or contribution, continue to:

- inspect licenses of mandatory dependencies
- decide desired commercial reuse posture
- decide whether hosted modifications should be shared
- consider contributor expectations
- consider institutional adoption friction

Release automation and public package publication remain deliberate maintainer actions; a license
selection alone does not authorize publication of artifacts or redistribution of source content.

## Source-content rights

The project license applies to our software, not imported research.

The system should make it possible to share:

- metadata that is permitted to be shared
- identifiers/citations
- derived structured facts where lawful
- user-generated extraction schemas and workflows

without necessarily sharing restricted raw source artifacts.

## Commercial use

A future paid service or downstream commercial research product requires a source-by-source rights audit. Making the software private does not erase obligations from open-source dependencies, contributor licenses, or data/content terms.

## Research integrity

Preserve:

- retractions/corrections
- conflicting evidence
- extraction uncertainty
- human corrections
- source versions

Never silently delete inconvenient contradictory evidence from a synthesis pipeline.

## Security milestones before institutional claims

- threat model
- authentication/authorization design
- tenancy tests
- secret scanning
- dependency/SBOM process
- artifact-upload hardening
- SSRF controls
- audit-log integrity
- backup/restore testing
- vulnerability disclosure policy
- reproducible deployment guidance
