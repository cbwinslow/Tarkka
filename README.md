# Tarkka

Tarkka is an open, agent-first research infrastructure platform for discovering, ingesting,
normalizing, organizing, and serving evidence-grounded research to humans and AI agents.

This repository is in its first implementation milestone. The core is intentionally usable without
an LLM, network connection, or hosted service.

## First vertical slice

```bash
python -m tarkka ingest ./notes.md
python -m tarkka inspect <document-id>
python -m tarkka read <document-id> --section 0
```

The initial local runtime stores immutable source artifacts by SHA-256 and persists normalized
metadata in a small JSON catalog. PostgreSQL is the reference production metadata store; its first
migration and connection boundary are included in this milestone.

See `docs/` for the architecture, canonical model, roadmap, agent interface, and security/rights
principles.
