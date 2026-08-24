# Research capabilities

`research_capabilities()` is Tarkka's compact, transport-neutral first response
for agent clients. It returns stable operation handles, short routing summaries,
and an estimated token cost before a client requests detailed schemas or data.

The index intentionally exposes only the currently implemented/usable families.
It is shared application behavior for future MCP, CLI, API, and SDK interfaces;
it neither selects a provider nor reads documents.
