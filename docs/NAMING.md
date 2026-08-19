# Naming

## Status

**Unresolved.** The repository currently uses `thoth`, but the final product/package name should change before public launch if possible.

## Why not Thoth?

The name is an excellent conceptual fit—Thoth is associated with writing, knowledge, and scribes—but an active open-source AI research project already uses **Thoth** for agentic systematic literature reviews, citation verification, and MCP access. That overlaps directly with this project's problem space and would create unnecessary confusion.

## Why not Mimir?

Mimir is also an excellent wisdom metaphor, but it is already heavily used across AI memory, knowledge, code research, and scientific-agent projects.

## Other names considered

### Nisaba

Sumerian goddess associated with writing, accounting, learning, and scribal knowledge. Conceptually one of the strongest fits for a system that structures research.

Concern: Google Research already has a software project named `nisaba`, though in an unrelated domain.

### Nabu

Mesopotamian god associated with writing and wisdom. Short and memorable.

Concern: already used by multiple software projects and resembles the established Nabu Casa brand.

### Seshat

Egyptian goddess of writing, recordkeeping, measurement, and knowledge. Near-perfect conceptual fit.

Concern: multiple current AI-agent/code-knowledge projects already use Seshat.

### Ma'at / Maat

Associated with truth, order, balance, and justice—good for evidence integrity.

Concern: existing active software and a recent agentic legal research project use the name.

### Sia

Egyptian personification of perception/understanding.

Concern: active AI framework uses SIA.

### Enki

Mesopotamian god associated with wisdom, intelligence, crafts, and creation.

Pros: broad fit for a system turning knowledge into useful work.

Concern: common technology/project name; uniqueness must be checked before selection.

### Heka

Egyptian concept/deity associated with magic and effective power.

Pros: short, memorable, less literal.

Concern: weaker semantic connection to evidence/research than writing/wisdom names.

### Crucible

Strong metaphor: raw material enters and is transformed/refined.

Pros: accurately describes the research-refinery idea.

Concern: extremely common software/product name and not a wisdom/knowledge figure.

## Naming criteria

The final name should ideally:

1. be easy to pronounce and spell
2. have a strong knowledge/evidence/research metaphor
3. avoid collision with active AI/research tools
4. have a reasonably unique GitHub/PyPI/npm/search footprint
5. work as a CLI/package namespace
6. not lock the platform to one domain
7. support a clear visual identity
8. avoid trademark confusion where practical

## Recommended approach

Before implementation reaches package publishing, perform a dedicated naming pass across:

- GitHub
- PyPI
- npm
- crates.io if relevant
- domain names
- general web search
- basic trademark screening

A unique compound name may be safer than another single mythological name. Examples of the pattern—not final recommendations—could combine a knowledge figure with the project's function, such as `Nisaba Research`, `Enki Evidence`, or an invented compound that can own its namespace.

## Decision deadline

Choose the final name **before**:

- publishing the Python package
- creating stable import paths
- publishing MCP registry entries
- producing logos/website assets
- recruiting external contributors at scale

Until then, internal code and documents should use neutral phrases such as `research platform`, `research core`, and `research service` whenever practical.
