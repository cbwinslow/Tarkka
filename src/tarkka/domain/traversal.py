from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy


class TraversalStatus(StrEnum):
    """Lifecycle state for one bounded traversal target."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class TraversalTarget:
    """One normalized target in a resumable traversal frontier."""

    target_id: UUID
    uri: str
    depth: int
    status: TraversalStatus = TraversalStatus.QUEUED
    attempts: int = 0
    bytes_acquired: int = 0
    discovery_link_ids: tuple[UUID, ...] = ()
    parent_target_ids: tuple[UUID, ...] = ()
    last_error: str | None = None

    def __post_init__(self) -> None:
        normalized_uri = normalize_http_uri(self.uri, field_name="traversal target URI")
        if not isinstance(self.depth, int) or isinstance(self.depth, bool) or self.depth < 0:
            raise ValueError("traversal target depth must be a non-negative integer")
        if not isinstance(self.status, TraversalStatus):
            raise ValueError("traversal target status must be a TraversalStatus")
        if not isinstance(self.attempts, int) or isinstance(self.attempts, bool) or self.attempts < 0:
            raise ValueError("traversal target attempts must be a non-negative integer")
        if (
            not isinstance(self.bytes_acquired, int)
            or isinstance(self.bytes_acquired, bool)
            or self.bytes_acquired < 0
        ):
            raise ValueError("traversal target bytes_acquired must be a non-negative integer")
        if self.last_error is not None and (
            not isinstance(self.last_error, str) or not self.last_error.strip()
        ):
            raise ValueError("traversal target last_error must be non-blank when provided")
        object.__setattr__(self, "uri", normalized_uri)
        object.__setattr__(self, "discovery_link_ids", _unique_uuids(self.discovery_link_ids))
        object.__setattr__(self, "parent_target_ids", _unique_uuids(self.parent_target_ids))


@dataclass(frozen=True, slots=True)
class TraversalCheckpoint:
    """Immutable, restart-safe traversal frontier plus acquisition budget counters."""

    checkpoint_id: UUID
    targets: tuple[TraversalTarget, ...] = ()
    budget: AcquisitionBudgetState = AcquisitionBudgetState()

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint_id, UUID):
            raise ValueError("traversal checkpoint ID must be a UUID")
        targets = tuple(self.targets)
        if any(not isinstance(target, TraversalTarget) for target in targets):
            raise ValueError("traversal checkpoint targets must be TraversalTarget values")
        if len({target.target_id for target in targets}) != len(targets):
            raise ValueError("traversal checkpoint target IDs must be unique")
        if len({target.uri for target in targets}) != len(targets):
            raise ValueError("traversal checkpoint target URIs must be unique")
        if not isinstance(self.budget, AcquisitionBudgetState):
            raise ValueError("traversal checkpoint budget must be AcquisitionBudgetState")
        object.__setattr__(self, "targets", targets)

    def enqueue(
        self,
        uri: str,
        *,
        depth: int,
        discovery_link_id: UUID | None = None,
        parent_target_id: UUID | None = None,
    ) -> TraversalCheckpoint:
        """Add or enrich one normalized URI without duplicating the frontier target."""
        normalized_uri = normalize_http_uri(uri, field_name="traversal target URI")
        _require_depth(depth)
        if discovery_link_id is not None and not isinstance(discovery_link_id, UUID):
            raise ValueError("discovery link ID must be a UUID when provided")
        if parent_target_id is not None and not isinstance(parent_target_id, UUID):
            raise ValueError("parent target ID must be a UUID when provided")
        if parent_target_id is not None and self._target(parent_target_id) is None:
            raise ValueError("parent traversal target must already exist in the checkpoint")

        existing = next((target for target in self.targets if target.uri == normalized_uri), None)
        if existing is not None:
            discovery_ids = _append_uuid(existing.discovery_link_ids, discovery_link_id)
            parent_ids = _append_uuid(existing.parent_target_ids, parent_target_id)
            updated_depth = (
                min(existing.depth, depth)
                if existing.status is TraversalStatus.QUEUED
                else existing.depth
            )
            updated = replace(
                existing,
                depth=updated_depth,
                discovery_link_ids=discovery_ids,
                parent_target_ids=parent_ids,
            )
            return self._replace_target(updated)

        target = TraversalTarget(
            target_id=_target_id(self.checkpoint_id, normalized_uri),
            uri=normalized_uri,
            depth=depth,
            discovery_link_ids=(discovery_link_id,) if discovery_link_id else (),
            parent_target_ids=(parent_target_id,) if parent_target_id else (),
        )
        return replace(self, targets=(*self.targets, target))

    def next_eligible(
        self,
        policy: ResourceAcquisitionPolicy,
        *,
        seconds_since_last_request: float | None = None,
    ) -> TraversalTarget | None:
        """Return the first queued target allowed by URI and current budget policy."""
        if not isinstance(policy, ResourceAcquisitionPolicy):
            raise ValueError("traversal policy must be a ResourceAcquisitionPolicy")
        for target in self.targets:
            if target.status is not TraversalStatus.QUEUED:
                continue
            if not policy.allows_uri(target.uri):
                continue
            if self.budget.allows_request(
                policy,
                depth=target.depth,
                seconds_since_last_request=seconds_since_last_request,
            ):
                return target
        return None

    def start(
        self,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        seconds_since_last_request: float | None = None,
    ) -> TraversalCheckpoint:
        """Record one actual request attempt and move the target in progress."""
        target = self._require_target(target_id)
        if target.status is not TraversalStatus.QUEUED:
            raise ValueError("only queued traversal targets may be started")
        if not policy.allows_uri(target.uri) or not self.budget.allows_request(
            policy,
            depth=target.depth,
            seconds_since_last_request=seconds_since_last_request,
        ):
            raise ValueError("traversal target is not eligible under the acquisition policy")
        updated = replace(
            target,
            status=TraversalStatus.IN_PROGRESS,
            attempts=target.attempts + 1,
            last_error=None,
        )
        budget = AcquisitionBudgetState(
            requests_used=self.budget.requests_used + 1,
            bytes_used=self.budget.bytes_used,
            elapsed_seconds=self.budget.elapsed_seconds,
        )
        return replace(self._replace_target(updated), budget=budget)

    def complete(
        self,
        target_id: UUID,
        *,
        bytes_acquired: int,
        elapsed_seconds: float,
    ) -> TraversalCheckpoint:
        """Record a successful request and advance durable byte/time counters."""
        target = self._require_target(target_id)
        if target.status is not TraversalStatus.IN_PROGRESS:
            raise ValueError("only in-progress traversal targets may be completed")
        _require_non_negative_int(bytes_acquired, "completed bytes_acquired")
        _require_monotonic_elapsed(elapsed_seconds, self.budget.elapsed_seconds)
        updated = replace(
            target,
            status=TraversalStatus.COMPLETED,
            bytes_acquired=bytes_acquired,
            last_error=None,
        )
        budget = AcquisitionBudgetState(
            requests_used=self.budget.requests_used,
            bytes_used=self.budget.bytes_used + bytes_acquired,
            elapsed_seconds=elapsed_seconds,
        )
        return replace(self._replace_target(updated), budget=budget)

    def fail(
        self,
        target_id: UUID,
        *,
        error: str,
        elapsed_seconds: float,
    ) -> TraversalCheckpoint:
        """Record a failed request without losing its deterministic frontier identity."""
        target = self._require_target(target_id)
        if target.status is not TraversalStatus.IN_PROGRESS:
            raise ValueError("only in-progress traversal targets may fail")
        if not isinstance(error, str) or not error.strip():
            raise ValueError("traversal failure error must be a non-blank string")
        _require_monotonic_elapsed(elapsed_seconds, self.budget.elapsed_seconds)
        updated = replace(
            target,
            status=TraversalStatus.FAILED,
            last_error=error.strip(),
        )
        budget = AcquisitionBudgetState(
            requests_used=self.budget.requests_used,
            bytes_used=self.budget.bytes_used,
            elapsed_seconds=elapsed_seconds,
        )
        return replace(self._replace_target(updated), budget=budget)

    def requeue_failed(
        self,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
    ) -> TraversalCheckpoint:
        """Requeue a failed target only while the existing retry policy permits it."""
        target = self._require_target(target_id)
        if target.status is not TraversalStatus.FAILED:
            raise ValueError("only failed traversal targets may be requeued")
        retries_used = max(target.attempts - 1, 0)
        if not policy.allows_retry(retries_used):
            raise ValueError("traversal retry budget is exhausted")
        return self._replace_target(
            replace(target, status=TraversalStatus.QUEUED, last_error=None)
        )

    def skip(self, target_id: UUID, *, reason: str) -> TraversalCheckpoint:
        """Mark a queued target intentionally skipped without spending request budget."""
        target = self._require_target(target_id)
        if target.status is not TraversalStatus.QUEUED:
            raise ValueError("only queued traversal targets may be skipped")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("traversal skip reason must be a non-blank string")
        return self._replace_target(
            replace(
                target,
                status=TraversalStatus.SKIPPED,
                last_error=reason.strip(),
            )
        )

    def _target(self, target_id: UUID) -> TraversalTarget | None:
        return next((target for target in self.targets if target.target_id == target_id), None)

    def _require_target(self, target_id: UUID) -> TraversalTarget:
        if not isinstance(target_id, UUID):
            raise ValueError("traversal target ID must be a UUID")
        target = self._target(target_id)
        if target is None:
            raise ValueError("traversal target does not exist in the checkpoint")
        return target

    def _replace_target(self, updated: TraversalTarget) -> TraversalCheckpoint:
        return replace(
            self,
            targets=tuple(
                updated if target.target_id == updated.target_id else target
                for target in self.targets
            ),
        )


def _target_id(checkpoint_id: UUID, uri: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:{checkpoint_id}:traversal-target:{uri}")


def _append_uuid(values: tuple[UUID, ...], value: UUID | None) -> tuple[UUID, ...]:
    if value is None or value in values:
        return values
    return (*values, value)


def _unique_uuids(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
    normalized = tuple(values)
    if any(not isinstance(value, UUID) for value in normalized):
        raise ValueError("traversal provenance IDs must be UUID values")
    return tuple(dict.fromkeys(normalized))


def _require_depth(value: int) -> None:
    _require_non_negative_int(value, "traversal target depth")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_monotonic_elapsed(value: float, previous: float) -> None:
    state = AcquisitionBudgetState(elapsed_seconds=value)
    if state.elapsed_seconds < previous:
        raise ValueError("traversal elapsed_seconds must not move backwards")
