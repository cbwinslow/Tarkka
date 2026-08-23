from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from tarkka.application.http_acquisition import HttpAcquisitionError, HttpAcquisitionService
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

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000552")
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
    def __init__(self, *responses: HttpTransportResponse) -> None:
        self.responses = list(responses)
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
        return self.responses.pop(0)


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=1,
        max_requests=2,
        max_bytes=1024,
        max_retries=1,
        max_redirects=1,
        max_elapsed_seconds=30.0,
    )


def _service(
    tmp_path: Path,
    transport: _Transport,
) -> tuple[HttpAcquisitionService, _Resolver]:
    resolver = _Resolver()
    return (
        HttpAcquisitionService(
            resolver=resolver,
            transport=transport,
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            observation_repository=JsonSourceObservationRepository(
                tmp_path / "observations.json"
            ),
            checkpoint_repository=JsonTraversalCheckpointRepository(
                tmp_path / "checkpoints.json"
            ),
            clock=lambda: 10.0,
            sleeper=lambda _: None,
        ),
        resolver,
    )


def test_benign_query_target_acquires_without_duplicate_request_uri(tmp_path: Path) -> None:
    uri = "https://example.org/paper?id=5"
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(uri, depth=0)
    target_id = checkpoint.targets[0].target_id
    transport = _Transport(HttpTransportResponse(status_code=200, body=b"paper"))
    service, _ = _service(tmp_path, transport)

    result = service.acquire(checkpoint, target_id, _policy())

    assert result.checkpoint.targets[0].status is TraversalStatus.COMPLETED
    assert transport.calls[0]["uri"] == uri


def test_redacted_query_target_still_requires_transient_original_uri(tmp_path: Path) -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/paper?token=secret",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    transport = _Transport(HttpTransportResponse(status_code=200, body=b"paper"))
    service, resolver = _service(tmp_path, transport)

    with pytest.raises(ValueError, match="transient original"):
        service.acquire(checkpoint, target_id, _policy())

    assert resolver.calls == 0
    assert transport.calls == []


@pytest.mark.parametrize("location", [None, "", "   "])
def test_redirect_without_usable_location_fails_closed(
    tmp_path: Path,
    location: str | None,
) -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/start",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    headers = {} if location is None else {"Location": (location,)}
    transport = _Transport(
        HttpTransportResponse(status_code=302, headers=headers, body=b"redirect")
    )
    service, _ = _service(tmp_path, transport)

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy())

    assert caught.value.checkpoint.targets[0].status is TraversalStatus.FAILED
    assert len(transport.calls) == 1
