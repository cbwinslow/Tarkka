# Tarkka

Tarkka is an open, agent-first research infrastructure platform for discovering, ingesting,
normalizing, organizing, and serving evidence-grounded research to humans and AI agents.

The core is intentionally usable without an LLM, network connection, or hosted service. Rich
document parsing is optional and stays behind the same parser contract as the lightweight local
runtime.

## Local vertical slice

```bash
python -m tarkka ingest ./notes.md
python -m tarkka inspect <document-id>
python -m tarkka read <document-id> --section 0
```

The local runtime stores immutable source artifacts by SHA-256, records acquisition provenance,
and persists normalized metadata in a small JSON catalog. PostgreSQL is the reference production
metadata store.

## Rich document parsing

Install the optional Docling adapter for PDFs, DOCX, PPTX, HTML, images, and other formats supported
by the adapter:

```bash
python -m pip install -e '.[docling]'
tarkka ingest ./paper.pdf
```

Docling is an adapter, not a core dependency. Tarkka converts its output into the same canonical
`Document -> Section -> Passage` representation used by the built-in text parser.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy
pytest
```

GitHub Actions runs these checks across supported Python versions and separately verifies that the
optional Docling integration can be installed.

See `docs/` for the architecture, canonical model, roadmap, agent interface, context-efficiency
strategy, and security/rights principles.
