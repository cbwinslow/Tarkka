from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.http_acquisition import HttpAcquisitionService
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.traversal import TraversalCheckpoint
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.http_transport import HttpTransportResponse

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000001999")
_START = "https://example.org/start"
_REDIRECT = "https://cdn.example.org/final"
_START_ADDRESS = "93.184.216.34"
_REDIRECT_ADDRESS = "93.184.216.35"


class _HostMappedResolver:
    def __init__(self) -> None:
        self.addresses = {
            "example.org": (_START_ADDRESS,),
            "cdn.example.org": (_REDIRECT_ADDRESS,),
        }
        self.requests: list[tuple[str, float | None]] = []

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        self.requests.append((hostname, timeout_seconds))
        return self.addresses[hostname]


class _RedirectTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, int, float | None]] = []

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        self.requests.append(
            (uri, resolved_address, max_response_bytes, timeout_seconds)
        )
        if uri == _START:
            return HttpTransportResponse(
                status_code=302,
                headers={"Location": (_REDIRECT,)},
            )
        if uri == _REDIRECT:
            return HttpTransportResponse(status_code=200, body=b"research")
        raise AssertionError(f"unexpected URI: {uri}")


def test_redirect_resolves_and_connects_to_each_validated_hostname(tmp_path: Path) -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(_START, depth=0)
    target_id = checkpoint.targets[0].target_id
    resolver = _HostMappedResolver()
    transport = _RedirectTransport()
    policy = ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=2,
        max_requests=4,
        max_bytes=128,
        max_retries=1,
        max_redirects=2,
        max_elapsed_seconds=60.0,
        min_request_interval_seconds=0.0,
    )
    service = HttpAcquisitionService(
        resolver=resolver,
        transport=transport,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=JsonSourceObservationRepository(
            tmp_path / "observations.json"
        ),
        checkpoint_repository=JsonTraversalCheckpointRepository(
            tmp_path / "checkpoints.json"
        ),
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    result = service.acquire(checkpoint, target_id, policy)

    assert result.response.final_uri == _REDIRECT
    assert result.response.redirect_chain == (_REDIRECT,)
    assert [hostname for hostname, _ in resolver.requests] == [
        "example.org",
        "cdn.example.org",
    ]
    assert [request[:2] for request in transport.requests] == [
        (_START, _START_ADDRESS),
        (_REDIRECT, _REDIRECT_ADDRESS),
    ]
