# Rights and resource-use policy

Tarkka treats network retrieval, local storage, analysis, and redistribution as separate policy decisions. A service being technically reachable or allowed by `robots.txt` does not automatically grant permission for any of those downstream uses.

## Independent use decisions

`RightsAccessDecision` records explicit booleans for:

- `retrieve` — whether Tarkka may fetch the resource in the current policy context;
- `store` — whether Tarkka may persist a local copy;
- `analyze` — whether Tarkka may run extraction, indexing, models, or other analysis over the resource;
- `redistribute` — whether Tarkka may expose or republish the resource itself.

These values are intentionally independent. For example, a source may permit retrieval and private research analysis while prohibiting redistribution.

## Policy provenance

Every rights decision records:

- the normalized target URI;
- a non-blank policy/source name;
- an optional policy reference/version;
- whether authentication is required;
- whether the source is paywalled;
- whether an explicit operator override was applied;
- an auditable rationale when an operator override is used.

Credentials, session cookies, subscription tokens, passwords, and other secrets do not belong in this decision object.

## Operator overrides

Operator overrides are explicit values:

- `none` — no operator override;
- `restrict` — an operator intentionally made the source-derived decision stricter;
- `allow` — an operator intentionally changed the rights-layer decision to allow a use.

Any non-`none` override requires a rationale. The override is visible provenance, not hidden configuration.

An operator `allow` **cannot** override Tarkka's technical acquisition or robots safety boundary. `combine_crawl_eligibility()` always applies the technical/robots result first; a denial there remains a denial regardless of the rights-layer decision.

## Recursive crawl composition

Recursive acquisition should compose decisions in this order:

```text
ResourceAcquisitionPolicy
    -> robots decision
        -> rights retrieval decision
            -> eligible recursive fetch
```

`combine_crawl_eligibility()` preserves the full robots/technical `CrawlAccessDecision` and the full `RightsAccessDecision` inside the final `CrawlEligibilityDecision` rather than collapsing the evidence into one unexplained boolean.

Only `retrieval_allowed` participates in the recursive-fetch decision. Storage, analysis, and redistribution remain downstream checks and must be consulted at the point where those operations occur.

## Authentication and paywalls

`requires_authentication` and `paywalled` are descriptive policy facts. They do not contain credentials and they do not grant access. A caller may represent an authenticated, policy-approved context with `retrieval_allowed=True`, but bypassing authentication or access controls is outside Tarkka's crawler contract.

## Relationship to robots policy

See `docs/ROBOTS_ACCESS_POLICY.md` for the Robots Exclusion Protocol boundary. Robots rules are crawl guidance, not authorization. The rights layer addresses the separate question of whether Tarkka's intended use of a technically accessible resource is permitted by operator/source policy.

## Verification

Run the focused deterministic tests with:

```bash
uv run --no-sync pytest tests/test_rights_access_policy.py
```

The normal Python 3.11/3.12/3.13 CI matrix remains authoritative.
