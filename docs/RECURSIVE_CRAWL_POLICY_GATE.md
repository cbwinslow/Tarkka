# Recursive crawl policy gate

Recursive crawling uses a policy gate before a discovered target is handed to the generic HTTP acquisition service.

The gate deliberately distinguishes a permanent policy decision from a temporary inability to fetch:

- `READY` — technical bounds, a fresh robots policy, rights retrieval policy, and current pacing all permit acquisition;
- `ROBOTS_REFRESH_REQUIRED` — no fresh cache entry exists for the target authority;
- `DEFERRED_BUDGET` — current request/depth/byte/time budget does not permit another attempt yet;
- `DEFERRED_PACING` — robots or operator rate policy requires more time since the previous request;
- `SKIPPED` — technical scope, robots, or rights policy permanently denies this queued target in the current traversal policy.

## Ordering

For a queued discovered target with a fresh robots cache entry:

```text
technical URI + current budget
    -> fresh robots cache
        -> robots decision
            -> rights retrieval decision
                -> tightened request interval
                    -> READY / DEFERRED / SKIPPED
```

Technical URI denial is evaluated before cache lookup, so an out-of-scope target does not trigger a robots refresh. A robots or rights denial is persisted with `TraversalCheckpoint.skip()`.

## Budget semantics

A denied target is skipped before `TraversalCheckpoint.start()` and therefore consumes no target attempt and no request budget.

Budget exhaustion and pacing are temporary states. They leave the checkpoint unchanged rather than converting the target to `SKIPPED`.

The gate evaluates the target against the robots-derived effective minimum request interval. `Crawl-delay` may therefore defer a target even when the base `ResourceAcquisitionPolicy` interval would allow it.

## Acquisition boundary

`RecursiveCrawlPolicyGate` does **not** perform network I/O. A `READY` result exposes the effective `ResourceAcquisitionPolicy` that should be passed to the existing `HttpAcquisitionService` for the actual content target.

A cache miss is represented explicitly as `ROBOTS_REFRESH_REQUIRED`. The next #116 slice will satisfy that state by acquiring `/robots.txt` through the same bounded traversal/HTTP security machinery, then saving the resulting `RobotsCacheEntry` and re-evaluating the original queued target.

This keeps direct/user-requested `HttpAcquisitionService` calls independent of robots crawling policy while enforcing robots/rights rules for recursive discovery workflows.

## Verification

```bash
uv run --no-sync pytest tests/test_recursive_crawl_policy_gate.py
```
