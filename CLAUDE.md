# CLAUDE.md

This repository uses shared provider-neutral instructions in [`AGENTS.md`](AGENTS.md).

## Start here

Read `AGENTS.md` first. It contains the architectural invariants, task-to-document routing table, testing expectations, and progressive-disclosure rules used by all coding agents.

## Claude-specific context discipline

Use sequential context loading:

1. Read `AGENTS.md`.
2. Read only the architecture document(s) routed by the current task.
3. Search for existing symbols/contracts before opening broad directories or large documents.
4. Load reference/dependency documentation only when a decision actually depends on it.
5. Prefer concise summaries/handles from research tools; expand evidence or full documents only when required.

Do not eagerly ingest every file in `docs/`, `skills/`, or future domain packs into context.

## Skills

When `skills/` contains a relevant portable `SKILL.md`, read its frontmatter/summary first and follow its staged `load` guidance. Skills orchestrate repository/platform capabilities; they do not replace application logic.

## Architecture changes

If implementation requires changing a documented invariant, update the relevant design document in the same change and explain the tradeoff. Do not silently diverge from the architecture.
