# Citation resolution

Tarkka resolves preserved bibliography references to canonical Works only through exact identifier evidence in the deterministic resolution path.

## Resolution states

A `BibliographicReference` can produce:

- `resolved` — all matching canonical identifiers point to exactly one Work;
- `ambiguous` — exact identifiers point to two or more different Works;
- `unresolved` — no preserved identifier matches the current Work catalog;
- `rejected` — a domain state reserved for a later explicit human-review/workflow decision; the automatic exact resolver does not emit it.

Ambiguous references retain candidate Work IDs without selecting one. Unresolved references remain first-class citation state rather than being guessed from title or author similarity.

## Identifier behavior

The deterministic resolver:

- normalizes DOI resolver/scheme variants through Tarkka's canonical DOI rules;
- normalizes arXiv URL/prefix/version variants through Tarkka's canonical arXiv rules;
- performs exact lookup for other preserved identifier schemes;
- ignores malformed DOI/arXiv values for matching while leaving the source-native reference unchanged.

Canonical identifier values follow one contract across adapters: scheme names are lowercase, values are trimmed, adapters must use a shared normalizer from `tarkka.domain.identifiers` whenever Tarkka defines one for that scheme, and source-native unnormalized values remain preserved in the source/reference representation rather than being destructively rewritten. Until a shared normalizer exists for a scheme such as PMID or ISBN, an adapter may supply only an exact canonical value; it must not invent its own lossy normalization rule. When multiple adapters need non-trivial rules for another scheme, that rule belongs in the shared identifier module (or a future registry there), not duplicated independently in each adapter.

Fuzzy title, author, venue, or semantic matching is intentionally outside this service and must not silently create canonical identity.

## Citation relations

When the canonical Work corresponding to the citing document is known, a resolved bibliography reference can create a `CITES` `WorkRelation` from the citing Work to the cited Work. The relation is deterministic and retains:

- source document ID;
- source bibliography reference ID;
- source observation ID when available;
- `native` observation basis.

Repeated resolution reuses equivalent resolution and relation records rather than creating duplicate graph edges. Relation reuse is keyed directly by deterministic relation ID, avoiding scans over all outgoing citations. Before reuse, all deterministic relation direction, kind, basis, and provenance fields are verified; an incompatible stored record fails loudly instead of masking a collision or caller bug.

## CLI workflow

```bash
tarkka citations resolve <document-id>
# Or require a particular known canonical Work:
tarkka citations resolve <document-id> --citing-work <work-id>
# Resolve a bounded page of a large bibliography:
tarkka citations resolve <document-id> --offset 100 --limit 20
```

The CLI resolves every preserved reference through the exact deterministic path and returns compact
resolution and relation records. Without `--citing-work`, it uses the persisted Work-document link
when exactly one canonical Work represents the Document. Zero links still permits reference
resolution but creates no Work relation; multiple distinct links are an explicit error rather than
a silent identity choice. When links exist, an explicit Work must be one of those links. Resolution
returns and processes one bounded page (at most 100 references); callers advance with `--offset`.

## Persistence and concurrency

Resolution identity is content-based: `resolution_id` and all semantic/provenance fields participate in equivalence, while `resolved_at` records when the first equivalent result was persisted and is intentionally excluded from idempotency comparison. The `CitationRepository` port requires implementations to serialize writes to a reference's resolution key. The local JSON repository uses its exclusive file lock; a PostgreSQL adapter should enforce the same invariant with a unique constraint plus transactional `INSERT ... ON CONFLICT`/locking semantics.

Deterministic Work-relation insertion has a stronger repository contract: `get_or_create_relation` is atomic. Concurrent callers presenting the same relation identity and provenance receive the first persisted relation, including its original `created_at`, rather than handling a duplicate-write exception themselves. A `CitationConflictError` therefore means the stable relation ID is already associated with incompatible semantic/provenance content and should normally propagate for investigation; it is not a transient concurrency signal and callers should not retry it with backoff.
