from __future__ import annotations

import hashlib
from itertools import count
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.application.http_policy_fetch import (
    HttpPolicyFetchCommitError,
    HttpPolicyFetchService,
)
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.policy_fetch_finalization import PolicyFetchFinalization
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus
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

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.regression]

_ROBOTS_URI = "https://example.org/robots.txt"
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del timeout_seconds
        self.calls.append(hostname)
        return (_PUBLIC_ADDRESS,)


class _Transport:
    def __init__(self, response: HttpTransportResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        self.calls.append(
            {
                "uri": uri,
                "resolved_address": resolved_address,
                "max_response_bytes": max_response_bytes,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class _FailOnceObservationRepository:
    def __init__(self, delegate: JsonSourceObservationRepository) -> None:
        self.delegate = delegate
        self.failed = False

    def save_observation(self, observation: SourceObservation) -> None:
        if not self.failed:
            self.failed = True
            raise OSError("simulated observation commit interruption")
        self.delegate.save_observation(observation)

    def get_observation(self, observation_id: UUID) -> SourceObservation | None:
        return self.delegate.get_observation(observation_id)

    def save_resource_link(self, link: ResourceLinkObservation) -> None:
        self.delegate.save_resource_link(link)

    def list_resource_links(
        self,
        observation_id: UUID,
    ) -> tuple[ResourceLinkObservation, ...]:
        return self.delegate.list_resource_links(observation_id)


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=2,
        max_requests=5,
        max_bytes=1024,
        max_redirects=2,
        max_elapsed_seconds=60.0,
        min_request_interval_seconds=0.0,
    )


def _checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(uuid4()).enqueue(
        "https://example.org/article",
        depth=1,
    )
    return checkpoint, checkpoint.targets[0].target_id


def test_partial_observation_commit_retry_reuses_durable_fetch(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    resolver = _Resolver()
    expected_body = b"User-agent: *\nAllow: /\n"
    transport = _Transport(
        HttpTransportResponse(
            status_code=200,
            headers={"Content-Type": ("text/plain",)},
            body=expected_body,
        )
    )
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    failing_observations = _FailOnceObservationRepository(observations)
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    finalizations = JsonPolicyFetchFinalizationRepository(
        tmp_path / "policy-finalizations.json"
    )
    ticks = count(100.0, 0.25)
    interrupted = HttpPolicyFetchService(
        resolver=resolver,
        transport=transport,
        artifact_store=artifacts,
        observation_repository=failing_observations,
        checkpoint_repository=checkpoints,
        finalization_repository=finalizations,
        clock=lambda: next(ticks),
        sleeper=lambda _: None,
    )

    with pytest.raises(HttpPolicyFetchCommitError) as exc_info:
        interrupted.fetch(
            checkpoint,
            _policy(),
            uri=_ROBOTS_URI,
            depth=1,
        )

    failed_checkpoint = exc_info.value.checkpoint
    marker = finalizations.get(failed_checkpoint.checkpoint_id, _ROBOTS_URI)
    assert marker is not None
    assert artifacts.exists(marker.artifact_sha256)
    assert observations.get_observation(marker.observation_id) is None
    target = next(item for item in failed_checkpoint.targets if item.target_id == target_id)
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0
    network_calls = (tuple(resolver.calls), tuple(transport.calls))
    spent_budget = failed_checkpoint.budget

    recovered_service = HttpPolicyFetchService(
        resolver=resolver,
        transport=transport,
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=checkpoints,
        finalization_repository=finalizations,
        clock=lambda: next(ticks),
        sleeper=lambda _: None,
    )
    result = recovered_service.fetch(
        failed_checkpoint,
        _policy(),
        uri=_ROBOTS_URI,
        depth=1,
    )

    assert result.body == expected_body
    assert result.artifact.sha256 == marker.artifact_sha256
    assert result.observation.observation_id == marker.observation_id
    assert observations.get_observation(marker.observation_id) == result.observation
    assert finalizations.get(failed_checkpoint.checkpoint_id, _ROBOTS_URI) is None
    assert result.checkpoint.budget == spent_budget
    assert (tuple(resolver.calls), tuple(transport.calls)) == network_calls


def test_recovery_fails_closed_when_expected_artifact_is_missing(tmp_path: Path) -> None:
    checkpoint, _ = _checkpoint()
    resolver = _Resolver()
    transport = _Transport(HttpTransportResponse(status_code=200))
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    finalizations = JsonPolicyFetchFinalizationRepository(
        tmp_path / "policy-finalizations.json"
    )
    ticks = count(100.0, 0.25)
    service = HttpPolicyFetchService(
        resolver=resolver,
        transport=transport,
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=checkpoints,
        finalization_repository=finalizations,
        clock=lambda: next(ticks),
        sleeper=lambda _: None,
    )

    response = HttpTransportResponse(
        status_code=200,
        headers={"Content-Type": ("text/plain",)},
        body=b"not persisted",
    )
    snapshot = HttpResponseSnapshot(
        requested_uri=_ROBOTS_URI,
        final_uri=_ROBOTS_URI,
        status_code=response.status_code,
        headers=response.headers,
        depth=1,
    )
    digest = hashlib.sha256(response.body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    observation = snapshot.to_source_observation(native_artifact_id=artifact_id)
    marker = PolicyFetchFinalization(
        checkpoint_id=checkpoint.checkpoint_id,
        requested_uri=_ROBOTS_URI,
        artifact_sha256=digest,
        observation_id=observation.observation_id,
        response=snapshot,
    )
    finalizations.save(marker)
    network_calls = (tuple(resolver.calls), tuple(transport.calls))

    with pytest.raises(HttpPolicyFetchCommitError, match="artifact is not durable"):
        service.recover_policy_finalization(checkpoint, requested_uri=_ROBOTS_URI)

    assert finalizations.get(checkpoint.checkpoint_id, _ROBOTS_URI) == marker
    assert (tuple(resolver.calls), tuple(transport.calls)) == network_calls
