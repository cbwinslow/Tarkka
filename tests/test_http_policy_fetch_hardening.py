from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.application.http_policy_fetch import (
    HttpPolicyFetchCommitError,
    HttpPolicyFetchError,
    HttpPolicyFetchService,
)
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.models import Artifact
from tarkka.domain.policy_fetch_finalization import PolicyFetchFinalization
from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint
from tarkka.infrastructure.storage.json_policy_fetch_finalization_repository import (
    JsonPolicyFetchFinalizationRepository,
)
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.http_transport import HttpTransportResponse

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_POLICY_URI = "https://example.org/robots.txt"
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del hostname, timeout_seconds
        return (_PUBLIC_ADDRESS,)


class _Transport:
    def __init__(self, outcomes: list[HttpTransportResponse | Exception]) -> None:
        self.outcomes = list(outcomes)

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        del uri, resolved_address, max_response_bytes, timeout_seconds
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _UnreadableArtifactStore(LocalArtifactStore):
    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        del sha256
        raise OSError("injected read failure")


class _CorruptReadArtifactStore(LocalArtifactStore):
    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        del sha256
        return b"corrupt"


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


class _FailingFinalizationRepository(JsonPolicyFetchFinalizationRepository):
    def save(self, finalization: PolicyFetchFinalization) -> None:
        del finalization
        raise OSError("injected finalization save failure")


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 5,
        "max_bytes": 1024,
        "max_redirects": 2,
        "max_elapsed_seconds": 60.0,
        "min_request_interval_seconds": 0.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _checkpoint(*, budget: AcquisitionBudgetState | None = None) -> TraversalCheckpoint:
    return TraversalCheckpoint(
        uuid4(),
        budget=budget or AcquisitionBudgetState(),
    ).enqueue("https://example.org/article", depth=1)


def _service(
    tmp_path: Path,
    *,
    artifacts: LocalArtifactStore | None = None,
    finalizations: JsonPolicyFetchFinalizationRepository | None = None,
    transport: _Transport | None = None,
    clock: object = None,
    sleeper: object = None,
) -> HttpPolicyFetchService:
    kwargs: dict[str, object] = {}
    if clock is not None:
        kwargs["clock"] = clock
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    return HttpPolicyFetchService(
        resolver=_Resolver(),
        transport=transport or _Transport([HttpTransportResponse(status_code=200, body=b"ok")]),
        artifact_store=artifacts or LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=JsonSourceObservationRepository(tmp_path / "observations.json"),
        checkpoint_repository=JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json"),
        finalization_repository=finalizations
        or JsonPolicyFetchFinalizationRepository(tmp_path / "policy-finalizations.json"),
        **kwargs,  # type: ignore[arg-type]
    )


def _marker(
    checkpoint_id: UUID,
    body: bytes,
    *,
    requested_uri: str = _POLICY_URI,
) -> PolicyFetchFinalization:
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    snapshot = HttpResponseSnapshot(
        requested_uri=requested_uri,
        final_uri=requested_uri,
        status_code=200,
        headers={"Content-Type": ("text/plain",)},
        depth=1,
    )
    observation = snapshot.to_source_observation(native_artifact_id=artifact_id)
    return PolicyFetchFinalization(
        checkpoint_id=checkpoint_id,
        requested_uri=requested_uri,
        artifact_sha256=digest,
        observation_id=observation.observation_id,
        response=snapshot,
    )


def test_policy_fetch_rejects_out_of_policy_uri_before_network(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="outside the acquisition policy"):
        service.fetch(
            _checkpoint(),
            _policy(allowed_domains=frozenset({"other.example"})),
            uri=_POLICY_URI,
            depth=1,
        )


def test_recover_policy_finalization_requires_marker(tmp_path: Path) -> None:
    checkpoint = _checkpoint()

    with pytest.raises(HttpPolicyFetchCommitError, match="marker does not exist"):
        _service(tmp_path).recover_policy_finalization(
            checkpoint,
            requested_uri=_POLICY_URI,
        )


def test_policy_recovery_wraps_durable_artifact_read_failure(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    artifacts = _UnreadableArtifactStore(tmp_path / "artifacts")
    marker = _marker(checkpoint.checkpoint_id, b"expected")
    LocalArtifactStore.put_bytes(artifacts, b"expected")
    finalizations = JsonPolicyFetchFinalizationRepository(tmp_path / "policy-finalizations.json")
    finalizations.save(marker)
    service = _service(tmp_path, artifacts=artifacts, finalizations=finalizations)

    with pytest.raises(HttpPolicyFetchCommitError, match="unable to read durable policy artifact"):
        service.recover_policy_finalization(checkpoint, requested_uri=_POLICY_URI)


def test_policy_recovery_rejects_changed_artifact_bytes(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    artifacts = _CorruptReadArtifactStore(tmp_path / "artifacts")
    marker = _marker(checkpoint.checkpoint_id, b"expected")
    LocalArtifactStore.put_bytes(artifacts, b"expected")
    finalizations = JsonPolicyFetchFinalizationRepository(tmp_path / "policy-finalizations.json")
    finalizations.save(marker)
    service = _service(tmp_path, artifacts=artifacts, finalizations=finalizations)

    with pytest.raises(HttpPolicyFetchCommitError, match="artifact identity changed"):
        service.recover_policy_finalization(checkpoint, requested_uri=_POLICY_URI)


def test_policy_recovery_wraps_unexpected_artifact_store_identity(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    artifacts = _WrongIdentityArtifactStore(tmp_path / "artifacts")
    marker = _marker(checkpoint.checkpoint_id, b"expected")
    LocalArtifactStore.put_bytes(artifacts, b"expected")
    finalizations = JsonPolicyFetchFinalizationRepository(tmp_path / "policy-finalizations.json")
    finalizations.save(marker)
    service = _service(tmp_path, artifacts=artifacts, finalizations=finalizations)

    with pytest.raises(HttpPolicyFetchCommitError, match="recovery interrupted: RuntimeError"):
        service.recover_policy_finalization(checkpoint, requested_uri=_POLICY_URI)


def test_policy_finish_wraps_finalization_journal_failure(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    finalizations = _FailingFinalizationRepository(tmp_path / "policy-finalizations.json")
    service = _service(tmp_path, finalizations=finalizations, clock=lambda: 0.0)

    with pytest.raises(HttpPolicyFetchCommitError, match="persist policy output finalization"):
        service.fetch(checkpoint, _policy(), uri=_POLICY_URI, depth=1)


def test_policy_finish_wraps_unexpected_artifact_identity(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    artifacts = _WrongIdentityArtifactStore(tmp_path / "artifacts")
    service = _service(tmp_path, artifacts=artifacts, clock=lambda: 0.0)

    with pytest.raises(HttpPolicyFetchCommitError, match="output commit interrupted: RuntimeError"):
        service.fetch(checkpoint, _policy(), uri=_POLICY_URI, depth=1)


def test_policy_fetch_requires_location_for_redirect(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        transport=_Transport([HttpTransportResponse(status_code=302)]),
        clock=lambda: 0.0,
    )

    with pytest.raises(HttpPolicyFetchError) as caught:
        service.fetch(_checkpoint(), _policy(), uri=_POLICY_URI, depth=1)

    assert isinstance(caught.value.__cause__, ValueError)
    assert "requires a Location" in str(caught.value.__cause__)


def test_policy_fetch_rejects_redirect_outside_policy(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        transport=_Transport(
            [
                HttpTransportResponse(
                    status_code=302,
                    headers={"Location": ("https://other.example/robots.txt",)},
                )
            ]
        ),
        clock=lambda: 0.0,
    )

    with pytest.raises(HttpPolicyFetchError) as caught:
        service.fetch(_checkpoint(), _policy(), uri=_POLICY_URI, depth=1)

    assert isinstance(caught.value.__cause__, ValueError)
    assert "redirect target is not allowed" in str(caught.value.__cause__)


def test_policy_followup_rejects_interval_larger_than_elapsed_budget(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    policy = _policy(min_request_interval_seconds=2.0, max_elapsed_seconds=1.0)
    active = replace(checkpoint, budget=replace(checkpoint.budget, requests_used=1))
    service = _service(tmp_path, clock=lambda: 0.0)

    with pytest.raises(ValueError, match="wait would exceed elapsed-time budget"):
        service._wait_for_policy_followup(active, policy, 1, 0.0)


def test_policy_followup_rejects_exhausted_request_budget(tmp_path: Path) -> None:
    checkpoint = _checkpoint(budget=AcquisitionBudgetState(requests_used=1))
    policy = _policy(max_requests=1)
    service = _service(tmp_path, clock=lambda: 0.0)

    with pytest.raises(ValueError, match="redirect request exceeds the acquisition budget"):
        service._wait_for_policy_followup(checkpoint, policy, 1, 0.0)


def test_policy_followup_sleeps_for_positive_interval(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    policy = _policy(min_request_interval_seconds=0.25)
    sleeps: list[float] = []
    service = _service(tmp_path, clock=lambda: 0.0, sleeper=sleeps.append)

    service._wait_for_policy_followup(checkpoint, policy, 1, 0.0)

    assert sleeps == [0.25]
