# Naming

## Status

**Resolved for implementation:** **Tarkka**.

The GitHub repository may display as `Tarkka`, but all code-facing namespaces remain lowercase:

- Python package: `tarkka`
- CLI: `tarkka`
- environment prefix: `TARKKA_`
- default configuration naming: `tarkka.*`
- future MCP/package identifiers should prefer lowercase `tarkka` where the ecosystem allows it

## Why Tarkka?

`Tarkka` is short, distinctive, easy to pronounce, and semantically aligned with precision, exactness, and careful research. It is less crowded in the AI/research tooling space than many mythological wisdom names considered during project discovery.

The name also avoids implying that the core belongs to one research domain or one LLM/provider.

## Names considered and rejected

### Thoth

Excellent conceptual fit—writing, knowledge, and scribes—but an active open-source AI research project already uses Thoth for agentic systematic literature reviews, citation verification, and MCP access. The overlap is too direct.

### Mimir

Strong wisdom metaphor but heavily used across AI memory, knowledge, code research, and scientific-agent projects.

### Seshat

Near-perfect Egyptian writing/recordkeeping fit, but already used by several current agent/runtime/knowledge projects.

### Noema / Noesis

Excellent philosophical meanings, but both collide with active AI memory/research systems.

### Nisaba / Nabu / Enki / Ma'at / Sia / Heka / Hikma / Imbas

All were considered for their associations with wisdom, writing, perception, truth, or knowledge. Each had either meaningful software/AI collisions, weaker project semantics, or a less ownable namespace than Tarkka.

## Naming invariant

Do not introduce capitalized `Tarkka` into Python import paths, CLI commands, module names, database schemas, environment variables, or machine-facing identifiers unless an external system explicitly requires capitalization.

Human-facing prose and headings may use **Tarkka**.

## Pre-release validation

Before publishing a stable package or commercial service, repeat a lightweight collision check across:

- PyPI
- npm if relevant
- MCP registries
- GitHub
- domains
- basic trademark search

The implementation namespace is now stable enough to code against; a later legal/brand check can still identify conflicts before a 1.0 release.
