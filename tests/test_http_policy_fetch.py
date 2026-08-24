from __future__ import annotations

from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from tarkka.application.http_policy_fetch import (
    HttpPolicyFetchError,
    HttpPolicyFetchService,
)
from tarkka.domain.resource_acquisition import AcquisitionBudgetState, ResourceAcquisitionPolicy
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

_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self, values: dict[str, tuple[str, ...]]) -> None:
        self.values = values
        self.calls: list[str] = []

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del timeout_seconds
        self.calls.append(hostname)
        return self.values.get(hostname, ())


class _Transport:
    def __init__(self, outcomes: list[HttpTransportResponse | Exception]) -> None:
        self.outcomes = list(outcomes)
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
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 5,
        "max_bytes": 1024,
        "max_redirects": 3,
        "max_elapsed_seconds": 60.0,
        "min_request_interval_seconds": 0.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _checkpoint() -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(uuid4()).enqueue(
        "https://example.org/article",
        depth=1,
    )
    return checkpoint, checkpoint.targets[0].target_id


def _service(
    tmp_path: Path,
    *,
    resolver: _Resolver,
    transport: _Transport,
) -> tuple[
    HttpPolicyFetchService,
    JsonTraversalCheckpointRepository,
    JsonSourceObservationRepository,
    LocalArtifactStore,
]:
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    finalizations = JsonPolicyFetchFinalizationRepository(
        tmp_path / "policy-finalizations.json"
    )
    ticks = count(100.0, 0.5)
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
    return service, checkpoints, observations, artifacts


def test_policy_fetch_charges_budget_without_starting_frontier_target(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=200,
                headers={"Content-Type": ("text/plain",)},
                body=b"User-agent: *\nAllow: /\n",
            )
        ]
    )
    service, checkpoints, observations, artifacts = _service(
        tmp_path,
        resolver=resolver,
        transport=transport,
    )

    result = service.fetch(
        checkpoint,
        _policy(),
        uri="https://example.org/robots.txt",
        depth=1,
    )

    target = next(item for item in result.checkpoint.targets if item.target_id == target_id)
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0
    assert result.checkpoint.budget.requests_used == 1
    assert result.checkpoint.budget.bytes_used == len(result.body)
    assert result.checkpoint.budget.elapsed_seconds > 0
    assert result.body == b"User-agent: *\nAllow: /\n"
    assert artifacts.exists(result.artifact.sha256)
    assert observations.get_observation(result.observation.observation_id) == result.observation
    assert checkpoints.get(checkpoint.checkpoint_id) == result.checkpoint


def test_policy_fetch_follows_redirects_and_charges_each_request(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=302,
                headers={"Location": ("/robots-v2.txt",)},
                body=b"redirect",
            ),
            HttpTransportResponse(
                status_code=200,
                headers={"Content-Type": ("text/plain",)},
                body=b"User-agent: *\nDisallow: /private\n",
            ),
        ]
    )
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    result = service.fetch(
        checkpoint,
        _policy(),
        uri="https://example.org/robots.txt",
        depth=1,
    )

    target = next(item for item in result.checkpoint.targets if item.target_id == target_id)
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0
    assert result.checkpoint.budget.requests_used == 2
    assert result.checkpoint.budget.bytes_used == len(b"redirect") + len(result.body)
    assert result.response.final_uri == "https://example.org/robots-v2.txt"
    assert result.response.redirect_chain == ("https://example.org/robots-v2.txt",)
    assert [call["uri"] for call in transport.calls] == [
        "https://example.org/robots.txt",
        "https://example.org/robots-v2.txt",
    ]


def test_policy_fetch_rejects_unsafe_dns_and_preserves_spent_request(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    resolver = _Resolver({"example.org": ("127.0.0.1",)})
    transport = _Transport([])
    service, checkpoints, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpPolicyFetchError) as exc_info:
        service.fetch(
            checkpoint,
            _policy(),
            uri="https://example.org/robots.txt",
            depth=1,
        )

    failed = exc_info.value.checkpoint
    target = next(item for item in failed.targets if item.target_id == target_id)
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0
    assert failed.budget.requests_used == 1
    assert failed.budget.bytes_used == 0
    assert checkpoints.get(checkpoint.checkpoint_id) == failed
    assert transport.calls == []


def test_policy_fetch_respects_shared_request_budget_before_network(tmp_path: Path) -> None:
    checkpoint, _ = _checkpoint()
    checkpoint = TraversalCheckpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        targets=checkpoint.targets,
        budget=AcquisitionBudgetState(requests_used=5),
    )
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport([])
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(ValueError, match="exceeds the acquisition budget"):
        service.fetch(
            checkpoint,
            _policy(max_requests=5),
            uri="https://example.org/robots.txt",
            depth=1,
        )

    assert resolver.calls == []
    assert transport.calls == []


def test_policy_fetch_rejects_transport_overflow_and_preserves_spent_budget(
    tmp_path: Path,
) -> None:
    checkpoint, target_id = _checkpoint()
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=200,
                headers={"Content-Type": ("text/plain",)},
                body=b"x" * 16,
                limit_exceeded=True,
            )
        ]
    )
    service, checkpoints, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpPolicyFetchError) as exc_info:
        service.fetch(
            checkpoint,
            _policy(max_bytes=16),
            uri="https://example.org/robots.txt",
            depth=1,
        )

    failed = exc_info.value.checkpoint
    target = next(item for item in failed.targets if item.target_id == target_id)
    assert target.status is TraversalStatus.QUEUED
    assert target.attempts == 0
    assert failed.budget.requests_used == 1
    assert failed.budget.bytes_used == 16
    assert checkpoints.get(checkpoint.checkpoint_id) == failed
