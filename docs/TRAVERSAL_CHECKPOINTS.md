# Traversal checkpoints

Issue #28 needs resumable crawling without mixing network behavior into discovery adapters or duplicating acquisition policy.

`TraversalCheckpoint` is an immutable state machine that composes the existing `ResourceAcquisitionPolicy` and `AcquisitionBudgetState` contracts. It does not perform HTTP requests itself.

## Frontier state

Each normalized URI has one deterministic `TraversalTarget` identity per checkpoint. Rediscovery of the same secret-safe URI enriches the existing target rather than duplicating it:

- minimum queued depth;
- all distinct `ResourceLinkObservation` IDs that discovered it;
- all distinct parent traversal targets;
- request attempt count;
- acquired bytes;
- lifecycle status and terminal reason.

Lifecycle states are `queued`, `in_progress`, `completed`, `failed`, and `skipped`.

## Policy and budget reuse

`next_eligible()` and `start()` delegate URI scope, depth, request-count, elapsed-time, byte-budget, and rate-limit decisions to the already-established acquisition policy. Starting a target records the request attempt immediately so a crash cannot erase spent request budget.

A successful completion adds acquired bytes and elapsed time. A failure preserves the attempt and can be requeued only while `ResourceAcquisitionPolicy.max_retries` permits another try. Skipping a queued target records a reason without consuming request budget.

## Restart behavior

`JsonTraversalCheckpointRepository` atomically replaces evolving checkpoint state under the existing local file lock. A checkpoint restored with `in_progress` targets calls `recover_interrupted()` before traversal resumes. Those targets become `failed` with an explicit interruption reason while their already-counted request attempts remain spent; normal retry policy then decides whether they can be requeued.

```text
ResourceLinkObservation[]
    -> checkpoint.enqueue(...)
    -> next_eligible(policy)
    -> checkpoint.start(...)
    -> persist checkpoint
    -> external acquisition attempt
    -> complete(...) / fail(...)
    -> persist checkpoint
```

## Concurrency boundary

The JSON repository is a local **single-writer** checkpoint store. Its lock prevents partial local writes, but it is not a distributed queue or lease system. A future multi-worker crawler should introduce explicit revision/CAS or lease semantics rather than weakening this deterministic state contract.

## Run focused tests

```bash
uv run --no-sync pytest tests/test_traversal_checkpoints.py
```

If a resumed crawl appears stuck, inspect targets left in `in_progress`; restored checkpoints should run `recover_interrupted()` before selecting the next eligible target. Then inspect the persisted budget counters and the active `ResourceAcquisitionPolicy` limits before changing queue state.
