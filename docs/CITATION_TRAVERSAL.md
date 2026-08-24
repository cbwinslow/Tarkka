# Bounded citation traversal

Tarkka can traverse persisted `WorkRelation` records without requiring a graph database. Traversal is deterministic, cycle-safe, and bounded before it becomes a discovery or acquisition mechanism.

The local CLI exposes this graph inspection without widening the boundary:

```bash
tarkka citations traverse <work-id> --max-depth 1 --max-works 50
```

It returns stable Work IDs and provenance-backed relation summaries. The CLI accepts only
bounded depth (at most 5), Work count (at most 100), and relation count (at most 500);
it does not fetch, discover, resolve, or acquire any external source.

## Local traversal policy

`CitationTraversalPolicy` places hard limits on:

- maximum graph depth;
- maximum distinct Works returned, including the root;
- maximum Work relations returned;
- direction: outbound, inbound, or both;
- allowed `WorkRelationKind` values.

The default policy follows outbound `CITES` relations by one hop. Results preserve a deterministic breadth-first ordering and report which local bound stopped traversal when the graph extends beyond the requested budget. A zero-depth traversal reports `depth` when eligible relations exist and reports completion only when the root has no eligible relation. Likewise, reaching the final depth reports truncation for any omitted eligible edge, even when that edge points back to an already visited Work.

A relation is never returned if doing so would expose a new Work beyond `max_works`, and relation count never exceeds `max_relations`. Revisited Works do not expand the visited set, which makes cycles safe.

Traversal bounds are pushed into the `CitationRepository` query boundary. Relation queries accept allowed kinds, already-seen relation IDs, and a hard result limit. Local JSON storage still must read its catalog file, but it keeps only the bounded smallest matching relation set instead of materializing and sorting every adjacency. Production SQL adapters should translate the same contract into indexed `WHERE` predicates plus `ORDER BY ... LIMIT`.

## Local graph bounds vs acquisition bounds

This service traverses **already-persisted** relations only. It performs no HTTP requests, provider lookups, crawling, or document acquisition, so request-, byte-, retry-, domain-, and wall-clock budgets do not belong in this local graph layer.

When cited/citing traversal is connected to external discovery, that orchestration must compose this local policy with the bounded acquisition policy from the web/resource discovery layer. External expansion must remain explicitly bounded by request count, bytes, time, domains, retries, and depth rather than treating graph traversal as permission for unbounded network discovery.

This separation keeps local research-graph queries deterministic and cheap while preserving a clear safety boundary for future provider-backed cited/citing expansion.
