# Tarkka

Tarkka is an open, agent-first research infrastructure platform for discovering, ingesting,
normalizing, organizing, and serving evidence-grounded research to humans and AI agents.

## License and releases

Tarkka is licensed under [Apache-2.0](LICENSE). The license covers Tarkka software and
project-authored documentation; it does not grant rights to research content acquired, processed,
or referenced by Tarkka. Releases and public package publication are maintainer-controlled and
will be announced through tagged GitHub releases.

The core is intentionally usable without an LLM, hosted service, or mandatory external API. External
research providers, document parsers, databases, and future model providers live behind replaceable
contracts.

## Prove a research result in five minutes

Tarkka is designed to make research state inspectable and replayable rather than hide evidence
behind an answer-generation interface. The repository includes a completely local walkthrough that
uses a project-authored source fixture and the real CLI to demonstrate:

```text
preserved source
  -> normalized Document
  -> Claim + exact Evidence
  -> `tarkka why` provenance
  -> schema-v3 proof bundle
  -> offline verification
  -> exact deterministic replay
```

The walkthrough needs no model, provider credentials, PostgreSQL server, or network access. From a
checkout with Python 3.11 or newer, it can run directly through `PYTHONPATH=src python -m tarkka`
without an installation step. See [`docs/QUICKSTART_PROOF_REPLAY.md`](docs/QUICKSTART_PROOF_REPLAY.md).

## What works today

### Local research ingestion

```bash
tarkka ingest ./notes.md
tarkka inspect <document-id>
tarkka read <document-id> --section 0

# Extract deterministic sentence-level claims with exact passage evidence.
tarkka extract claims <document-id> --extractor rule
tarkka claims list <document-id>
tarkka claims show <claim-id>

# Walk a Claim back through extraction, exact Evidence, Document, and Artifact provenance.
tarkka why <claim-id>

# Export, independently verify, and replay portable research state.
tarkka bundle create <document-id> --schema-version 3 --output research.tarkka
tarkka bundle verify research.tarkka
tarkka replay research.tarkka

# For JATS, LaTeX, EPUB, and semantic HTML: inspect preserved citations progressively.
tarkka citations list <document-id> --limit 20
tarkka citations show <document-id> <reference-id>
tarkka citations resolve <document-id>
# Traverse only locally persisted citation relations; this does not fetch sources.
tarkka citations traverse <work-id> --max-depth 1 --max-works 50

# Inspect preserved supplements, datasets, software, and alternate representations.
tarkka resources list <document-id> --limit 20
tarkka resources show <document-id> <resource-link-id>

# Record and inspect reviewable claim-to-evidence assessments.
tarkka verify record <claim-id> --kind supports --evidence <evidence-id> \
  --verifier human-review --verifier-version 1 --confidence 0.9
tarkka verify list <claim-id>
tarkka verify show <relation-id>

# Start agent/tool discovery with a small operation index, then load one schema.
tarkka capabilities list
tarkka capabilities show research.verify.candidates

# Expand normalized source content progressively, from a manifest to one section.
tarkka documents manifest <document-id>
tarkka documents sections <document-id> --limit 20
tarkka documents section <document-id> <section-id>
tarkka documents package <document-id> --section <section-id> --section <section-id>
tarkka documents package <document-id> --section <section-id> --save
tarkka documents saved-package <context-package-id>
```

Tarkka stores immutable source artifacts by SHA-256, records acquisition provenance, normalizes
content into `Document -> Section -> Passage`, and exposes compact manifests before full content.
Native-structure parsers also preserve bibliography entries, inline citations, and exact contexts;
the citation CLI lists compact references before expanding a single reference's source text/context.
`citations resolve` performs exact identifier resolution and creates a native `cites` relation only
when the citing Work is explicit or uniquely linked to the Document.
They also preserve source-observed resource relationships; the resources CLI follows the same
compact-list then explicit-detail pattern without fetching or identity-resolving a target.
Verification assessments are separately auditable and expand back to their exact source evidence.

Install the optional Docling integration for richer formats such as PDF, DOCX, PPTX, HTML, and
images:

```bash
python -m pip install -e '.[docling]'
tarkka ingest ./paper.pdf
```

Docling is an adapter, not a core dependency.

### Scholarly discovery

```bash
# Default AUTO policy (currently prefers OpenAlex for broad discovery)
tarkka discover "machine learning MLB game outcome prediction"

# One provider
tarkka discover "pitcher fatigue" --provider semantic-scholar

# Selected providers
tarkka discover "baseball forecasting" \
  --provider openalex \
  --provider crossref

# Exhaustive enabled-provider fan-out
tarkka discover "baseball forecasting" --provider all
```

Current scholarly adapters:

- OpenAlex
- Crossref
- Semantic Scholar

Discovery supports provider selection, bounded concurrent fan-out, retries/rate-limit handling,
provider-specific continuation cursors, DOI-first deduplication, and reproducible SearchSnapshots.
Providers remain independent adapters; cross-provider identity and enrichment happen in application
services rather than providers calling one another.

Work and document persistence use local JSON by default and therefore need no database service. To
opt into PostgreSQL, install the optional extra and select the backend explicitly; a database URL
alone never changes the default. On a new database, apply the current schema migrations first:

```bash
uv sync --extra postgres
export TARKKA_DATABASE_URL=postgresql://localhost/tarkka
tarkka db upgrade
TARKKA_WORK_BACKEND=postgres \
tarkka work show <work-id>

TARKKA_DOCUMENT_BACKEND=postgres \
tarkka documents manifest <document-id>
```

Install the optional MCP transport to expose the same staged research services to an MCP client over
stdio:

```bash
uv sync --extra mcp
tarkka-mcp
```

MCP uses the same transport-neutral application contracts for progressive capability discovery,
bounded Document expansion, Claim lineage, and safe path-free persisted-Document replay. Start with
`research_capabilities`, expand only the operation schema needed for the task, and then invoke the
specific read operation. Remote replay accepts a stable Document handle rather than a caller-supplied
server filesystem path.

For transparent, opt-in local telemetry, set a JSONL destination before starting the server. Events
contain only tool name, outcome/error code, response byte count, estimated tokens, and latency;
they never contain document text, request arguments, or identifiers:

```bash
export TARKKA_MCP_TELEMETRY_PATH=./var/tarkka-mcp-usage.jsonl
tarkka-mcp
```

## Agent-first design

Tarkka uses progressive disclosure to conserve context:

```text
capabilities
  -> manifests
  -> summaries / structured findings
  -> evidence
  -> full sections/documents
  -> raw artifacts
```

Agents should retrieve the smallest representation that can answer the current question, then expand
only when necessary. See `AGENTS.md`, `CLAUDE.md`, and `docs/CONTEXT_EFFICIENCY.md`.

`AGENTS.md` is the shared repository instruction file for Codex, Claude, and other coding agents.
`CLAUDE.md` contains only Claude-specific context-loading guidance so architectural rules are not
duplicated.

The first portable staged skill is available at:

```text
skills/research-discovery/SKILL.md
```

## Architecture principles

- provider-neutral and domain-neutral core
- no LLM required for core operation
- immutable content-addressed raw artifacts
- provenance as a first-class concern
- claims, evidence, and citations remain distinct
- rights/access/redistribution policy modeled separately from software licensing
- PostgreSQL is the reference production metadata store
- adapters/plugins remain replaceable
- domain-specific semantics belong in domain packs
- CLI/API/MCP/SDK should share application services

## Current roadmap position

Tarkka now has a complete auditable proof/replay vertical slice: immutable source preservation,
deterministic normalization, evidence-backed Claims, provenance inspection, portable v1/v2/v3 proof
bundles, offline verification, exact deterministic replay, and safe replay/lineage serving to agents.

The immediate product sequence is:

```text
five-minute offline proof/replay adoption path
  -> frozen vs live research-state diff
  -> adapter/plugin conformance kit
  -> public evaluation corpus and interoperability work
```

See `docs/ROADMAP.md` and issue #198 for the broader product roadmap.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy
pytest
```

CI validates Ruff, strict mypy, and pytest across Python 3.11–3.13. Optional Docling integration is
verified separately with a CPU-only workflow.

## Documentation

For users, start with:

1. `docs/QUICKSTART_PROOF_REPLAY.md`
2. `docs/PROOF_BUNDLES.md`

For contributors and coding agents, start with:

1. `AGENTS.md`
2. `docs/PROJECT_CHARTER.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ROADMAP.md`

Then load task-specific documents on demand. The repository intentionally avoids requiring agents or
humans to read the entire documentation set before doing focused work.
