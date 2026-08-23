# Robots, rights, and crawl access policy

Tarkka separates three different questions that must not be collapsed into one boolean:

1. **Technical eligibility** — is the URI inside the explicit `ResourceAcquisitionPolicy` bounds and safe to acquire through Tarkka's HTTP transport?
2. **Robots eligibility** — does the service's Robots Exclusion Protocol policy permit this crawler product token to fetch the target?
3. **Rights/access eligibility** — does authentication, a paywall, source terms, licensing, or an operator policy restrict retrieval, storage, analysis, or redistribution?

Robots rules are not an authorization mechanism. A path being allowed by `robots.txt` does not grant permission to bypass authentication, defeat access controls, or redistribute content.

## Standards basis

The core robots behavior follows RFC 9309 (Robots Exclusion Protocol):

- user-agent product-token matching is case-insensitive;
- rules from all groups matching the same product token are combined;
- the `*` group is used only when no specific product-token group matches;
- `Allow`/`Disallow` path matching starts at the beginning of the URI path/query;
- the longest matching rule wins;
- equal-length `Allow` and `Disallow` rules prefer `Allow`;
- `*` and terminal `$` special matching are supported;
- parseable lines remain effective even when neighboring lines are malformed;
- `/robots.txt` itself is implicitly allowed;
- percent-encoded unreserved ASCII and UTF-8 non-ASCII path values are normalized for comparison;
- at least 500 KiB of a robots file must be processable. Tarkka bounds parsing at 512 KiB.

`Crawl-delay` is a common extension, not part of RFC 9309. Tarkka accepts a finite non-negative value and uses it only to make pacing stricter. It can never reduce `ResourceAcquisitionPolicy.min_request_interval_seconds`.

## Fetch outcomes

The policy evaluator receives an injected `RobotsFetchResult`; it performs no network I/O. The result must be produced by the same bounded, SSRF-safe acquisition boundary used for other network resources.

Tarkka maps fetch outcomes as follows:

| Outcome | Typical HTTP result | Tarkka decision |
| --- | --- | --- |
| `success` | 2xx | parse and obey all parseable applicable rules |
| `unavailable` | 4xx | robots does not add a restriction; technical/rights policy still applies |
| `unreachable` | 5xx or network failure | fail closed: deny crawl eligibility |
| `redirect_limit_exceeded` | redirect chain exceeded | fail closed: deny crawl eligibility |

RFC 9309 permits a crawler that exceeds the recommended redirect-following threshold to treat robots as unavailable. Tarkka deliberately chooses the stricter deny behavior because a redirect loop or excessive chain is ambiguous and should not silently broaden crawl scope.

A robots result is accepted only for the exact scheme and authority of the target's canonical `/robots.txt` URI. A result fetched for another authority cannot be reused to authorize a target.

## Decision order

The evaluation order is intentionally one-way:

```text
raw target URI
    -> ResourceAcquisitionPolicy
        -> deny: stop
        -> allow: evaluate robots result
            -> deny: stop
            -> allow: continue to rights/access policy
```

Technical policy is evaluated against the original target URI before durable URI normalization. This prevents normalization/redaction from turning a URI containing forbidden credentials or another disallowed form into an eligible target.

Robots can tighten eligibility but can never override:

- domain/scheme allowlists;
- depth/request/byte/time budgets;
- redirect limits;
- DNS/IP/SSRF protections;
- rate limits already stricter than `Crawl-delay`;
- authentication or source-rights restrictions.

## Parser security

Robots content is untrusted input.

Tarkka's core matcher is dependency-free and deliberately bounded:

- maximum parsed content: 512 KiB;
- malformed/non-applicable lines are skipped while parseable rules remain effective;
- wildcard matching does not compile untrusted rules into regular expressions, avoiding regex-backtracking denial-of-service behavior;
- only RFC core `User-agent`, `Allow`, and `Disallow` directives affect eligibility;
- `Crawl-delay` is parsed separately as a pacing extension and cannot change rule grouping.

Do not replace this matcher with `urllib.robotparser.RobotFileParser` without a compatibility review. Current CPython `robotparser` behavior does not implement RFC 9309 longest-match precedence.

## Rights and access boundary

A future production crawler must compose robots decisions with an explicit source-rights/access decision before recursively fetching resources.

That layer should distinguish at least:

- public unauthenticated retrieval;
- authenticated/session-gated retrieval;
- paywalled or otherwise access-controlled content;
- locally stored/processed content;
- content that may be redistributed or republished;
- explicit operator/domain overrides and their provenance.

An operator override may choose a stricter policy. It must never weaken Tarkka's technical security checks, and any policy exception should be represented as provenance rather than hidden configuration.

## Caching and acquisition integration

This first contract is intentionally deterministic and network-free. It does not fetch or cache `robots.txt` itself.

When robots retrieval/caching is wired into recursive acquisition:

- retrieval must consume the existing request/byte/time budgets;
- redirects must pass the existing redirect/DNS/SSRF checks;
- cache age should normally not exceed 24 hours, consistent with RFC 9309, except where unreachable-service handling intentionally retains an earlier valid copy;
- the crawl decision and the robots observation used to make it should be provenance-visible;
- credentials, cookies, signed query values, and other secrets must not enter durable policy observations.

## Verification

Run the focused deterministic suite with:

```bash
uv run --no-sync pytest tests/test_robots_access_policy.py
```

The normal CI matrix remains authoritative across Python 3.11, 3.12, and 3.13.
