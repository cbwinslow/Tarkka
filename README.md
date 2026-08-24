# Tarkka

Tarkka is an open, agent-first research infrastructure platform for discovering, ingesting,
normalizing, organizing, and serving evidence-grounded research to humans and AI agents.

The core is intentionally usable without an LLM, hosted service, or mandatory external API. External
research providers, document parsers, databases, and future model providers live behind replaceable
contracts.

## What works today

### Local research ingestion

```bash
tarkka ingest ./notes.md
tarkka inspect <document-id>
tarkka read <document-id> --section 0

# For JATS, EPUB, and semantic HTML: inspect preserved citations progressively.
tarkka citations list <document-id> --limit 20
tarkka citations show <document-id> <reference-id>
tarkka citations resolve <document-id>

# Inspect preserved supplements, datasets, software, and alternate representations.
tarkka resources list <document-id> --limit 20
tarkka resources show <document-id> <resource-link-id>

# Record and inspect reviewable claim-to-evidence assessments.
tarkka verify record <claim-id> --kind supports --evidence <evidence-id> \
  --verifier human-review --verifier-version 1 --confidence 0.9
tarkka verify list <claim-id>
tarkka verify show <relation-id>
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

Work persistence uses local JSON by default (`~/.tarkka/works.json`) and therefore needs no database
service. To opt into the currently Work-only PostgreSQL backend, install the optional extra and set
both variables explicitly; a database URL alone never changes the default. On a new database, apply
the current Work schema migrations in order first:

```bash
uv sync --extra postgres
export TARKKA_DATABASE_URL=postgresql://localhost/tarkka
tarkka db upgrade
TARKKA_WORK_BACKEND=postgres \
tarkka work show <work-id>
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

Foundation and the first local ingestion milestones are complete. Scholarly discovery/identity is in
progress.

Immediate engineering sequence:

```text
persistent canonical Work identity
  -> external-ID aliases
  -> Crossref DOI enrichment
  -> arXiv adapter / richer routing
  -> finish scholarly identity
  -> structured extraction
       claims
       methods/models
       variables
       datasets/software
       metrics/results
       limitations
```

See `docs/ROADMAP.md` and `docs/MILESTONE_3.md` for details.

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

Start with:

1. `AGENTS.md`
2. `docs/PROJECT_CHARTER.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ROADMAP.md`

Then load task-specific documents on demand. The repository intentionally avoids requiring agents or
humans to read the entire documentation set before doing focused work.
