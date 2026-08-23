from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.http_acquisition import (
    HttpAcquisitionCommitError,
    HttpAcquisitionService,
)
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.source_observations import SourceObservation
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.http_transport import HttpTransportResponse

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000551")
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del hostname, timeout_seconds
        self.calls += 1
        return (_PUBLIC_ADDRESS,)


class _Transport:
    def __init__(self, response: HttpTransportResponse | None) -> None:
        self.response = response
        self.calls = 0

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        del uri, resolved_address, max_response_bytes, timeout_seconds
        self.calls += 1
        if self.response is None:
            raise AssertionError("recovery must not perform network I/O")
        response = self.response
        self.response = None
        return response


class _FailOnStatusRepository:
    def __init__(
        self,
        inner: JsonTraversalCheckpointRepository,
        *,
        fail_on_status: TraversalStatus,
    ) -> None:
        self.inner = inner
        self.fail_on_status = fail_on_status

    def save(self, checkpoint: TraversalCheckpoint) -> None:
        if any(target.status is self.fail_on_status for target in checkpoint.targets):
            raise OSError("injected checkpoint failure")
        self.inner.save(checkpoint)

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None:
        return self.inner.get(checkpoint_id)


class _FailingObservationRepository:
    def __init__(self, inner: JsonSourceObservationRepository) -> None:
        self.inner = inner

    def save_observation(self, observation: SourceObservation) -> None:
        del observation
        raise OSError("injected observation failure")

    def get_observation(self, observation_id: UUID) -> SourceObservation | None:
        return self.inner.get_observation(observation_id)


class _SaturatingClock:
    def __init__(self, *values: float) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> float:
        if not self.values:
            raise AssertionError("clock requires at least one value")
        index = min(self.index, len(self.values) - 1)
        self.index += 1
        return self.values[index]


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=1,
        max_requests=2,
        max_bytes=1024,
        max_retries=1,
        max_redirects=0,
        max_elapsed_seconds=30.0,
    )


def _checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/paper.txt",
        depth=0,
    )
    return checkpoint, checkpoint.targets[0].target_id


def _interrupted_finalization(
    tmp_path: Path,
) -> tuple[
    TraversalCheckpoint,
    UUID,
    JsonTraversalCheckpointRepository,
    JsonSourceObservationRepository,
    LocalArtifactStore,
]:
    checkpoint, target_id = _checkpoint()
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    service = HttpAcquisitionService(
        resolver=_Resolver(),
        transport=_Transport(HttpTransportResponse(status_code=200, body=b"research")),
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=_FailOnStatusRepository(
            checkpoints,
            fail_on_status=TraversalStatus.COMPLETED,
        ),
        clock=lambda: 10.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(HttpAcquisitionCommitError) as caught:
        service.acquire(checkpoint, target_id, _policy())
    return caught.value.checkpoint, target_id, checkpoints, observations, artifacts


def test_recovers_durable_outputs_after_final_checkpoint_write_fails(tmp_path: Path) -> None:
    finalizing, target_id, checkpoints, observations, artifacts = _interrupted_finalization(
        tmp_path
    )
    target = finalizing.targets[0]
    assert target.status is TraversalStatus.FINALIZING
    assert target.final_artifact_sha256 is not None
    assert target.final_observation_id is not None
    assert artifacts.exists(target.final_artifact_sha256)
    assert observations.get_observation(target.final_observation_id) is not None

    recovery_resolver = _Resolver()
    recovery_transport = _Transport(None)
    recovery = HttpAcquisitionService(
        resolver=recovery_resolver,
        transport=recovery_transport,
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=checkpoints,
        clock=_SaturatingClock(20.0, 23.5),
        sleeper=lambda _: None,
    )
    completed = recovery.recover_finalization(finalizing, target_id)

    assert completed.targets[0].status is TraversalStatus.COMPLETED
    assert completed.budget.elapsed_seconds == finalizing.budget.elapsed_seconds + 3.5
    assert checkpoints.get(_CHECKPOINT_ID) == completed
    assert recovery_resolver.calls == 0
    assert recovery_transport.calls == 0


def test_recovery_uses_newer_durable_completed_checkpoint(tmp_path: Path) -> None:
    finalizing, target_id, checkpoints, observations, artifacts = _interrupted_finalization(
        tmp_path
    )
    completed_elsewhere = finalizing.complete_finalization(
        target_id,
        elapsed_seconds=finalizing.budget.elapsed_seconds + 1.0,
    )
    checkpoints.save(completed_elsewhere)
    recovery = HttpAcquisitionService(
        resolver=_Resolver(),
        transport=_Transport(None),
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=checkpoints,
        clock=lambda: 50.0,
        sleeper=lambda _: None,
    )

    recovered = recovery.recover_finalization(finalizing, target_id)

    assert recovered == completed_elsewhere
    assert checkpoints.get(_CHECKPOINT_ID) == completed_elsewhere


def test_recovery_marks_missing_outputs_failed_so_target_can_retry(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    service = HttpAcquisitionService(
        resolver=_Resolver(),
        transport=_Transport(HttpTransportResponse(status_code=200, body=b"research")),
        artifact_store=artifacts,
        observation_repository=_FailingObservationRepository(observations),
        checkpoint_repository=checkpoints,
        clock=lambda: 10.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(HttpAcquisitionCommitError) as caught:
        service.acquire(checkpoint, target_id, _policy())

    finalizing = caught.value.checkpoint
    target = finalizing.targets[0]
    assert target.status is TraversalStatus.FINALIZING
    assert target.final_artifact_sha256 is not None
    assert artifacts.exists(target.final_artifact_sha256)

    recovery = HttpAcquisitionService(
        resolver=_Resolver(),
        transport=_Transport(None),
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=checkpoints,
        clock=lambda: 10.0,
        sleeper=lambda _: None,
    )
    with pytest.raises(HttpAcquisitionCommitError, match="marked failed for retry") as retry:
        recovery.recover_finalization(finalizing, target_id)

    failed = retry.value.checkpoint
    assert failed.targets[0].status is TraversalStatus.FAILED
    assert failed.targets[0].final_artifact_sha256 is None
    assert failed.targets[0].final_observation_id is None
    assert checkpoints.get(_CHECKPOINT_ID) == failed

    requeued = failed.requeue_failed(target_id, _policy())
    assert requeued.targets[0].status is TraversalStatus.QUEUED
