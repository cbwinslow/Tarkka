# Bounded citation traversal

Tarkka can traverse persisted `WorkRelation` records without requiring a graph database. Traversal is deterministic, cycle-safe, and bounded before it becomes a discovery or acquisition mechanism.

## Local traversal policy

`CitationTraversalPolicy` places hard limits on:

- maximum graph depth;
- maximum distinct Works returned, including the root;
- maximum Work relations returned;
- direction: outbound, inbound, or both;
- allowed `WorkRelationKind` values.

The default policy follows outbound `CITES` relations by one hop. Results preserve a deterministic breadth-first ordering and report which local bound stopped traversal when the graph extends beyond the requested budget.

A relation is never returned if doing so would expose a new Work beyond `max_works`, and relation count never exceeds `max_relations`. Revisited Works do not expand the visited set, which makes cycles safe.

## Local graph bounds vs acquisition bounds

This service traverses **already-persisted** relations only. It performs no HTTP requests, provider lookups, crawling, or document acquisition, so request-, byte-, retry-, domain-, and wall-clock budgets do not belong in this local graph layer.

When cited/citing traversal is connected to external discovery, that orchestration must compose this local policy with the bounded acquisition policy from the web/resource discovery layer. External expansion must remain explicitly bounded by request count, bytes, time, domains, retries, and depth rather than treating graph traversal as permission for unbounded network discovery.

This separation keeps local research-graph queries deterministic and cheap while preserving a clear safety boundary for future provider-backed cited/citing expansion.
