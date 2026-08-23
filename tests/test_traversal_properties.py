from __future__ import annotations

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000777")


def _policy(*, max_bytes: int = 100_000, max_requests: int = 20) -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=5,
        max_requests=max_requests,
        max_bytes=max_bytes,
        max_retries=3,
        max_elapsed_seconds=10_000.0,
    )


@pytest.mark.unit
@pytest.mark.property
@given(
    path=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=20,
    ),
    depth_a=st.integers(min_value=0, max_value=5),
    depth_b=st.integers(min_value=0, max_value=5),
)
def test_repeated_enqueue_is_idempotent_and_keeps_minimum_queued_depth(
    path: str,
    depth_a: int,
    depth_b: int,
) -> None:
    uri = f"https://example.org/{path}"
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(uri, depth=depth_a)
    target_id = checkpoint.targets[0].target_id

    repeated = checkpoint.enqueue(uri, depth=depth_b)

    assert len(repeated.targets) == 1
    assert repeated.targets[0].target_id == target_id
    assert repeated.targets[0].uri == checkpoint.targets[0].uri
    assert repeated.targets[0].depth == min(depth_a, depth_b)


@pytest.mark.unit
@pytest.mark.property
@given(
    bytes_acquired=st.integers(min_value=0, max_value=100_000),
    elapsed_seconds=st.floats(
        min_value=0,
        max_value=10_000,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_successful_completion_accounts_exact_bytes_and_monotonic_time(
    bytes_acquired: int,
    elapsed_seconds: float,
) -> None:
    policy = _policy(max_bytes=bytes_acquired)
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/resource",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id

    completed = checkpoint.start(target_id, policy).complete(
        target_id,
        bytes_acquired=bytes_acquired,
        elapsed_seconds=elapsed_seconds,
    )

    target = completed.targets[0]
    assert target.status is TraversalStatus.COMPLETED
    assert target.attempts == 1
    assert target.bytes_acquired == bytes_acquired
    assert completed.budget.requests_used == 1
    assert completed.budget.bytes_used == bytes_acquired
    assert completed.budget.elapsed_seconds == elapsed_seconds


@pytest.mark.unit
@pytest.mark.property
@given(
    first_elapsed=st.floats(
        min_value=0,
        max_value=9_999,
        allow_nan=False,
        allow_infinity=False,
    ),
    rollback=st.floats(
        min_value=0,
        max_value=1_000,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_elapsed_budget_never_moves_backwards(first_elapsed: float, rollback: float) -> None:
    policy = _policy()
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/resource",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    failed = checkpoint.start(target_id, policy).fail(
        target_id,
        error="retryable",
        elapsed_seconds=first_elapsed,
    )
    requeued = failed.requeue_failed(target_id, policy).start(target_id, policy)
    earlier = max(0.0, first_elapsed - rollback)

    if earlier < first_elapsed:
        with pytest.raises(ValueError, match="must not move backwards"):
            requeued.complete(
                target_id,
                bytes_acquired=0,
                elapsed_seconds=earlier,
            )
    else:
        completed = requeued.complete(
            target_id,
            bytes_acquired=0,
            elapsed_seconds=earlier,
        )
        assert completed.budget.elapsed_seconds == earlier


@pytest.mark.unit
@pytest.mark.property
@given(
    request_count=st.integers(min_value=1, max_value=10),
    max_requests=st.integers(min_value=1, max_value=10),
)
def test_request_budget_never_exceeds_policy_limit(
    request_count: int,
    max_requests: int,
) -> None:
    policy = _policy(max_requests=max_requests)
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID)
    for index in range(request_count):
        checkpoint = checkpoint.enqueue(f"https://example.org/{index}", depth=0)

    started = 0
    for target in checkpoint.targets:
        if checkpoint.next_eligible(policy) is None:
            break
        checkpoint = checkpoint.start(target.target_id, policy)
        checkpoint = checkpoint.complete(
            target.target_id,
            bytes_acquired=0,
            elapsed_seconds=checkpoint.budget.elapsed_seconds,
        )
        started += 1

    assert started == min(request_count, max_requests)
    assert checkpoint.budget.requests_used == started
    assert checkpoint.budget.requests_used <= policy.max_requests
