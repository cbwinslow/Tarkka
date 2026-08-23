from __future__ import annotations

from uuid import UUID

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000e01")
_URI = "https://example.org/resource"


class TraversalLifecycleMachine(RuleBasedStateMachine):
    """Exercise legal traversal lifecycle sequences and accounting invariants."""

    def __init__(self) -> None:
        super().__init__()
        self.policy = ResourceAcquisitionPolicy(
            allowed_domains=frozenset({"example.org"}),
            max_depth=5,
            max_requests=3,
            max_bytes=1_000,
            max_retries=2,
            max_elapsed_seconds=100.0,
        )
        self.checkpoint = TraversalCheckpoint(_CHECKPOINT_ID)
        self.target_id: UUID | None = None

    @initialize(depth=st.integers(min_value=0, max_value=5))
    def initialize_target(self, depth: int) -> None:
        self.checkpoint = self.checkpoint.enqueue(_URI, depth=depth)
        self.target_id = self.checkpoint.targets[0].target_id

    @rule(depth=st.integers(min_value=0, max_value=5))
    def enqueue_duplicate(self, depth: int) -> None:
        previous = self.checkpoint
        self._set_checkpoint(self.checkpoint.enqueue(_URI, depth=depth))
        assert len(self.checkpoint.targets) == 1
        assert self.checkpoint.targets[0].target_id == self._required_target_id()
        if previous.targets[0].status is not TraversalStatus.QUEUED:
            assert self.checkpoint.targets[0].depth == previous.targets[0].depth

    @precondition(
        lambda self: self._status() is TraversalStatus.QUEUED
        and self.checkpoint.next_eligible(self.policy) is not None
    )
    @rule()
    def start(self) -> None:
        self._set_checkpoint(
            self.checkpoint.start(self._required_target_id(), self.policy)
        )

    @precondition(lambda self: self._status() is TraversalStatus.IN_PROGRESS)
    @rule(bytes_acquired=st.integers(min_value=0, max_value=1_000))
    def complete(self, bytes_acquired: int) -> None:
        self._set_checkpoint(
            self.checkpoint.complete(
                self._required_target_id(),
                bytes_acquired=bytes_acquired,
                elapsed_seconds=self.checkpoint.budget.elapsed_seconds + 1.0,
            )
        )

    @precondition(lambda self: self._status() is TraversalStatus.IN_PROGRESS)
    @rule()
    def fail(self) -> None:
        self._set_checkpoint(
            self.checkpoint.fail(
                self._required_target_id(),
                error="generated failure",
                elapsed_seconds=self.checkpoint.budget.elapsed_seconds + 1.0,
            )
        )

    @precondition(lambda self: self._status() is TraversalStatus.IN_PROGRESS)
    @rule()
    def recover_interrupted(self) -> None:
        self._set_checkpoint(self.checkpoint.recover_interrupted())

    @precondition(lambda self: self._can_requeue())
    @rule()
    def requeue_failed(self) -> None:
        self._set_checkpoint(
            self.checkpoint.requeue_failed(self._required_target_id(), self.policy)
        )

    @precondition(lambda self: self._status() is TraversalStatus.QUEUED)
    @rule()
    def skip(self) -> None:
        self._set_checkpoint(
            self.checkpoint.skip(self._required_target_id(), reason="generated skip")
        )

    @invariant()
    def accounting_matches_target_state(self) -> None:
        target = self.checkpoint.targets[0]
        assert self.checkpoint.budget.requests_used == target.attempts
        expected_bytes = (
            target.bytes_acquired if target.status is TraversalStatus.COMPLETED else 0
        )
        assert self.checkpoint.budget.bytes_used == expected_bytes
        assert self.checkpoint.budget.requests_used <= self.policy.max_requests
        assert self.checkpoint.budget.elapsed_seconds >= 0

    @invariant()
    def target_identity_remains_stable(self) -> None:
        target = self.checkpoint.targets[0]
        assert target.target_id == self._required_target_id()
        assert target.uri == _URI
        assert len(self.checkpoint.targets) == 1

    def _required_target_id(self) -> UUID:
        if self.target_id is None:
            raise AssertionError("state machine target has not been initialized")
        return self.target_id

    def _status(self) -> TraversalStatus:
        return self.checkpoint.targets[0].status

    def _can_requeue(self) -> bool:
        if self._status() is not TraversalStatus.FAILED:
            return False
        attempts = self.checkpoint.targets[0].attempts
        retries_used = max(attempts - 1, 0)
        return self.policy.allows_retry(retries_used)

    def _set_checkpoint(self, updated: TraversalCheckpoint) -> None:
        assert updated.budget.elapsed_seconds >= self.checkpoint.budget.elapsed_seconds
        self.checkpoint = updated


TestTraversalLifecycle = TraversalLifecycleMachine.TestCase
TestTraversalLifecycle.settings = settings(
    max_examples=100,
    stateful_step_count=25,
    deadline=None,
)
