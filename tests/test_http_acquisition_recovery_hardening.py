from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.application.http_acquisition import (
    HttpAcquisitionCommitError,
    HttpAcquisitionService,
    _redirect_location,
)
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.models import Artifact
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.http_transport import HttpTransportResponse
from tarkka.ports.traversal import TraversalCheckpointRepository

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_PUBLIC_ADDRESS = "93.184.216.34"
_URI = "https://example.org/paper.txt"


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
    def __init__(self, response: HttpTransportResponse | None = None) -> None:
        self.response = response or HttpTransportResponse(status_code=200, body=b"research")
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
        return self.response


class _FailOnStatusRepository:
    def __init__(
        self,
        inner: JsonTraversalCheckpointRepository,
        *,
        status: TraversalStatus,
    ) -> None:
        self.inner = inner
        self.status = status

    def save(self, checkpoint: TraversalCheckpoint) -> None:
        if any(target.status is self.status for target in checkpoint.targets):
            raise OSError("injected checkpoint save failure")
        self.inner.save(checkpoint)

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None:
        return self.inner.get(checkpoint_id)


class _WrongIdentityArtifactStore(LocalArtifactStore):
    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        artifact = super().put_bytes(
            data,
            original_name=original_name,
            source_uri=source_uri,
            media_type=media_type,
        )
        return replace(artifact, artifact_id=uuid4())


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 5,
        "max_bytes": 1024,
        "max_retries": 1,
        "max_redirects": 2,
        "max_elapsed_seconds": 60.0,
        "min_request_interval_seconds": 0.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _queued() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(uuid4()).enqueue(_URI, depth=0)
    return checkpoint, checkpoint.targets[0].target_id


def _outputs(body: bytes) -> tuple[str, UUID, HttpResponseSnapshot]:
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    snapshot = HttpResponseSnapshot(
        requested_uri=_URI,
        final_uri=_URI,
        status_code=200,
        headers={"Content-Type": ("text/plain",)},
        depth=0,
    )
    observation = snapshot.to_source_observation(native_artifact_id=artifact_id)
    return digest, observation.observation_id, snapshot


def _finalizing(
    body: bytes = b"research",
) -> tuple[TraversalCheckpoint, UUID, HttpResponseSnapshot]:
    checkpoint, target_id = _queued()
    active = checkpoint.start(target_id, _policy())
    digest, observation_id, snapshot = _outputs(body)
    finalizing = active.begin_finalization(
        target_id,
        artifact_sha256=digest,
        observation_id=observation_id,
        elapsed_seconds=active.budget.elapsed_seconds,
    )
    return finalizing, target_id, snapshot


def _service(
    tmp_path: Path,
    *,
    checkpoints: TraversalCheckpointRepository | None = None,
    artifacts: LocalArtifactStore | None = None,
    observations: JsonSourceObservationRepository | None = None,
    resolver: _Resolver | None = None,
    transport: _Transport | None = None,
) -> HttpAcquisitionService:
    return HttpAcquisitionService(
        resolver=resolver or _Resolver(),
        transport=transport or _Transport(),
        artifact_store=artifacts or LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=observations
        or JsonSourceObservationRepository(tmp_path / "observations.json"),
        checkpoint_repository=checkpoints
        or JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json"),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )


def test_recovery_requires_authoritative_durable_checkpoint(tmp_path: Path) -> None:
    finalizing, target_id, _ = _finalizing()

    with pytest.raises(HttpAcquisitionCommitError, match="checkpoint is not durable"):
        _service(tmp_path).recover_finalization(finalizing, target_id)


def test_recovery_rejects_changed_durable_output_identity(tmp_path: Path) -> None:
    supplied, target_id, _ = _finalizing(b"supplied")
    reset_target = replace(
        supplied.targets[0],
        status=TraversalStatus.IN_PROGRESS,
        final_artifact_sha256=None,
        final_observation_id=None,
    )
    durable_active = replace(supplied, targets=(reset_target,))
    other_digest, other_observation_id, _ = _outputs(b"durable")
    durable = durable_active.begin_finalization(
        target_id,
        artifact_sha256=other_digest,
        observation_id=other_observation_id,
        elapsed_seconds=durable_active.budget.elapsed_seconds,
    )
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    checkpoints.save(durable)

    with pytest.raises(HttpAcquisitionCommitError, match="durable identity changed"):
        _service(tmp_path, checkpoints=checkpoints).recover_finalization(supplied, target_id)


def test_recovery_detects_durable_state_change_with_same_empty_identity(tmp_path: Path) -> None:
    checkpoint, target_id = _queued()
    active = checkpoint.start(target_id, _policy())
    supplied = active.complete(target_id, bytes_acquired=0, elapsed_seconds=0.0)
    durable = active.fail(target_id, error="changed elsewhere", elapsed_seconds=0.0)
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    checkpoints.save(durable)

    with pytest.raises(HttpAcquisitionCommitError, match="durable state already changed"):
        _service(tmp_path, checkpoints=checkpoints).recover_finalization(supplied, target_id)


def test_recovery_wraps_failure_to_persist_retryable_failed_state(tmp_path: Path) -> None:
    finalizing, target_id, _ = _finalizing()
    durable = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    durable.save(finalizing)
    failing = _FailOnStatusRepository(durable, status=TraversalStatus.FAILED)

    with pytest.raises(
        HttpAcquisitionCommitError,
        match="outputs are missing and retry state could not be saved",
    ):
        _service(tmp_path, checkpoints=failing).recover_finalization(finalizing, target_id)


def test_recovery_rejects_observation_linked_to_other_artifact(tmp_path: Path) -> None:
    body = b"expected"
    finalizing, target_id, _ = _finalizing(body)
    expected_digest = hashlib.sha256(body).hexdigest()
    wrong_digest, _, wrong_snapshot = _outputs(b"other")
    wrong_artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{wrong_digest}")
    wrong_observation = wrong_snapshot.to_source_observation(native_artifact_id=wrong_artifact_id)
    durable_target = replace(
        finalizing.targets[0],
        final_observation_id=wrong_observation.observation_id,
    )
    durable = replace(finalizing, targets=(durable_target,))

    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    checkpoints.save(durable)
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    artifact = artifacts.put_bytes(body, source_uri=_URI, media_type="text/plain")
    assert artifact.sha256 == expected_digest
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    observations.save_observation(wrong_observation)

    with pytest.raises(HttpAcquisitionCommitError, match="unexpected artifact"):
        _service(
            tmp_path,
            checkpoints=checkpoints,
            artifacts=artifacts,
            observations=observations,
        ).recover_finalization(durable, target_id)


def test_recovery_wraps_final_completed_checkpoint_write_failure(tmp_path: Path) -> None:
    body = b"research"
    finalizing, target_id, snapshot = _finalizing(body)
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    observation = snapshot.to_source_observation(native_artifact_id=artifact_id)

    durable = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    durable.save(finalizing)
    failing = _FailOnStatusRepository(durable, status=TraversalStatus.COMPLETED)
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    artifacts.put_bytes(body, source_uri=_URI, media_type="text/plain")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    observations.save_observation(observation)

    with pytest.raises(HttpAcquisitionCommitError, match="completion is still interrupted"):
        _service(
            tmp_path,
            checkpoints=failing,
            artifacts=artifacts,
            observations=observations,
        ).recover_finalization(finalizing, target_id)


def test_finish_wraps_unexpected_artifact_store_identity(tmp_path: Path) -> None:
    checkpoint, target_id = _queued()
    artifacts = _WrongIdentityArtifactStore(tmp_path / "artifacts")

    with pytest.raises(HttpAcquisitionCommitError, match="output commit interrupted: RuntimeError"):
        _service(tmp_path, artifacts=artifacts).acquire(checkpoint, target_id, _policy())


def test_request_once_rejects_disallowed_uri_before_dns(tmp_path: Path) -> None:
    checkpoint, target_id = _queued()
    policy = _policy()
    active = checkpoint.start(target_id, policy)
    resolver = _Resolver()
    service = _service(tmp_path, resolver=resolver)

    with pytest.raises(ValueError, match="request URI is not allowed"):
        service._request_once(
            active,
            policy,
            "https://other.example/resource",
            started_at=0.0,
        )

    assert resolver.calls == 0


def test_followup_rejects_exhausted_request_budget(tmp_path: Path) -> None:
    checkpoint, target_id = _queued()
    policy = _policy(max_requests=1)
    active = checkpoint.start(target_id, policy)

    with pytest.raises(ValueError, match="redirect request exceeds the acquisition budget"):
        _service(tmp_path)._wait_for_followup(
            active,
            active.targets[0],
            policy,
            started_at=0.0,
        )


@pytest.mark.parametrize(
    ("location", "message"),
    [
        ("\x01", "control characters"),
        ("//:80", "invalid authority"),
    ],
)
def test_redirect_location_rejects_control_characters_and_invalid_authority(
    location: str,
    message: str,
) -> None:
    response = HttpTransportResponse(status_code=302, headers={"Location": (location,)})

    with pytest.raises(ValueError, match=message):
        _redirect_location(response)
