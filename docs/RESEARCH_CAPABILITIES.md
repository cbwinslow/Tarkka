# Research capabilities

`research_capabilities()` is Tarkka's compact, transport-neutral first response
for agent clients. It returns stable operation handles, short routing summaries,
and an estimated token cost before a client requests detailed schemas or data.

The index intentionally exposes only the currently implemented/usable families.
It is shared application behavior for future MCP, CLI, API, and SDK interfaces;
it neither selects a provider nor reads documents.

`research.discover` maps to `DiscoveryService.discover`; `research.verify` maps
to `EvidenceVerificationService.record`; and `research.verify.candidates` maps
to its bounded citation-context review aid; `research.verify.context` expands
one returned local context handle. `research.citations.traverse` exposes the
existing bounded local citation graph traversal. Handle resolution and named deeper
representations are deliberately not advertised until their application
services exist. The token estimate includes a documented fixed envelope
overhead plus each returned operation's estimate; it is a routing estimate, not
metered usage.

After selecting a handle, callers use `research_operation_schema(operation_id)`
to load only that operation's compact input descriptor, allowed enum values,
result summary, and estimate. It raises a typed unknown-operation error rather
than silently advertising a future operation. This is the second staged
discovery step, still shared application behavior for future MCP, CLI, API, and
SDK layers.

The dependency-free CLI exposes the same staged contract for people, scripts, and
agent runtimes that have not yet adopted an MCP transport:

```bash
tarkka capabilities list
tarkka capabilities show research.verify.candidates
```

Both commands return deterministic JSON. `list` contains only the compact index;
`show` loads the selected operation's descriptor. Neither command reads research
documents, selects a provider, or executes an operation.

The current document retrieval ladder is likewise available through shared
application behavior and the CLI. It intentionally lists compact normalized
section handles before expanding a single exact section and its passages:

```bash
tarkka documents manifest <document-id>
tarkka documents sections <document-id> --limit 20
tarkka documents section <document-id> <section-id>
```

The `research.documents.*` operations advertise these three steps. A section
expansion returns only the requested section's normalized passages; it does not
silently flatten or retrieve the whole document.

For an agent that has already selected exact sections, `tarkka documents package`
builds a bounded context package with its manifest, exact section/passage provenance,
and a deterministic token estimate. It requires one or more distinct `--section`
handles, never chooses or expands sections implicitly, and rejects selections above
the 8,000-token content budget so callers can split them deliberately.

Pass `--save` to retain that explicit selection as a `context_package:<uuid>` handle;
`tarkka documents saved-package <context-package-id>` resolves it later through the
same bounded source-preserving package service.
