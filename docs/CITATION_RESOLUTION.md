# Citation resolution

Tarkka resolves preserved bibliography references to canonical Works only through exact identifier evidence in the deterministic resolution path.

## Resolution states

A `BibliographicReference` can produce:

- `resolved` — all matching canonical identifiers point to exactly one Work;
- `ambiguous` — exact identifiers point to two or more different Works;
- `unresolved` — no preserved identifier matches the current Work catalog;
- `rejected` — reserved for explicit review/workflow decisions rather than automatic exact matching.

Ambiguous references retain candidate Work IDs without selecting one. Unresolved references remain first-class citation state rather than being guessed from title or author similarity.

## Identifier behavior

The deterministic resolver:

- normalizes DOI resolver/scheme variants through Tarkka's canonical DOI rules;
- normalizes arXiv URL/prefix/version variants through Tarkka's canonical arXiv rules;
- performs exact lookup for other preserved identifier schemes;
- ignores malformed DOI/arXiv values for matching while leaving the source-native reference unchanged.

Fuzzy title, author, venue, or semantic matching is intentionally outside this service and must not silently create canonical identity.

## Citation relations

When the canonical Work corresponding to the citing document is known, a resolved bibliography reference can create a `CITES` `WorkRelation` from the citing Work to the cited Work. The relation is deterministic and retains:

- source document ID;
- source bibliography reference ID;
- source observation ID when available;
- `native` observation basis.

Repeated resolution reuses equivalent resolution and relation records rather than creating duplicate graph edges.
