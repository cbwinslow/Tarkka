from __future__ import annotations

import math
from dataclasses import replace

from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint


def begin_policy_request(
    checkpoint: TraversalCheckpoint,
    policy: ResourceAcquisitionPolicy,
    *,
    depth: int,
    expected_bytes: int = 0,
    seconds_since_last_request: float | None = None,
) -> TraversalCheckpoint:
    """Charge one auxiliary policy request without mutating traversal target lifecycle."""
    if not isinstance(checkpoint, TraversalCheckpoint):
        raise ValueError("policy request checkpoint must be a TraversalCheckpoint")
    if not isinstance(policy, ResourceAcquisitionPolicy):
        raise ValueError("policy request policy must be a ResourceAcquisitionPolicy")
    if not checkpoint.budget.allows_request(
        policy,
        depth=depth,
        expected_bytes=expected_bytes,
        seconds_since_last_request=seconds_since_last_request,
    ):
        raise ValueError("policy request exceeds the acquisition budget")
    return replace(
        checkpoint,
        budget=AcquisitionBudgetState(
            requests_used=checkpoint.budget.requests_used + 1,
            bytes_used=checkpoint.budget.bytes_used,
            elapsed_seconds=checkpoint.budget.elapsed_seconds,
        ),
    )


def record_policy_response_bytes(
    checkpoint: TraversalCheckpoint,
    *,
    bytes_acquired: int,
) -> TraversalCheckpoint:
    """Record response bytes consumed by one auxiliary policy request."""
    if not isinstance(checkpoint, TraversalCheckpoint):
        raise ValueError("policy request checkpoint must be a TraversalCheckpoint")
    if (
        not isinstance(bytes_acquired, int)
        or isinstance(bytes_acquired, bool)
        or bytes_acquired < 0
    ):
        raise ValueError("policy response bytes_acquired must be a non-negative integer")
    return replace(
        checkpoint,
        budget=AcquisitionBudgetState(
            requests_used=checkpoint.budget.requests_used,
            bytes_used=checkpoint.budget.bytes_used + bytes_acquired,
            elapsed_seconds=checkpoint.budget.elapsed_seconds,
        ),
    )


def record_policy_elapsed(
    checkpoint: TraversalCheckpoint,
    *,
    elapsed_seconds: float,
) -> TraversalCheckpoint:
    """Record final elapsed time for an auxiliary policy request sequence."""
    _require_elapsed(checkpoint, elapsed_seconds)
    return replace(
        checkpoint,
        budget=AcquisitionBudgetState(
            requests_used=checkpoint.budget.requests_used,
            bytes_used=checkpoint.budget.bytes_used,
            elapsed_seconds=float(elapsed_seconds),
        ),
    )


def _require_elapsed(checkpoint: TraversalCheckpoint, elapsed_seconds: float) -> None:
    if not isinstance(checkpoint, TraversalCheckpoint):
        raise ValueError("policy request checkpoint must be a TraversalCheckpoint")
    if not isinstance(elapsed_seconds, (int, float)) or isinstance(elapsed_seconds, bool):
        raise ValueError("policy request elapsed_seconds must be numeric")
    if (
        not math.isfinite(float(elapsed_seconds))
        or elapsed_seconds < checkpoint.budget.elapsed_seconds
    ):
        raise ValueError("policy request elapsed_seconds must be finite and monotonic")
