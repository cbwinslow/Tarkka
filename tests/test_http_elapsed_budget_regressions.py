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

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000553")
_PUBLIC_ADDRESS = "93.184.216.34"


class _Clock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> float:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class _Resolver:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del hostname
        self.timeouts.append(timeout_seconds)
        return (_PUBLIC_ADDRESS,)


class _Transport:
    def __init__(self, responses: list[HttpTransportResponse]) -> None:
        self.responses = responses
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
        max_requests=3,
        max_bytes=1024,
        max_retries=1,
        max_redirects=2,
        max_elapsed_seconds=10.0,
    )


def _service(
    tmp_path: Path,
    *,
    clock: _Clock,
    resolver: _Resolver,
    transport: _Transport,
) -> HttpAcquisitionService:
    return HttpAcquisitionService(
        resolver=resolver,
        transport=transport,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=JsonSourceObservationRepository(tmp_path / "observations.json"),
        checkpoint_repository=JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json"),
        clock=clock,
        sleeper=lambda _: None,
    )


def test_redirect_hops_receive_shrinking_elapsed_deadlines(tmp_path: Path) -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/start",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    resolver = _Resolver()
    transport = _Transport(
        [
            HttpTransportResponse(status_code=302, headers={"Location": ("/final",)}, body=b"go"),
            HttpTransportResponse(status_code=200, body=b"done"),
        ]
    )
    # start=0; DNS/transport checks advance through 1,2,3 for hop one and 4,5,6 for hop two.
    service = _service(
        tmp_path,
        clock=_Clock([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.0, 6.0]),
        resolver=resolver,
        transport=transport,
    )

    result = service.acquire(checkpoint, target_id, _policy())

    assert result.checkpoint.targets[0].status is TraversalStatus.COMPLETED
    assert len(resolver.timeouts) == 2
    assert resolver.timeouts[0] is not None
    assert resolver.timeouts[1] is not None
    assert resolver.timeouts[1] < resolver.timeouts[0]
    assert transport.calls[1]["timeout_seconds"] < transport.calls[0]["timeout_seconds"]


def test_exhausted_elapsed_budget_stops_before_followup_transport(tmp_path: Path) -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/start",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    resolver = _Resolver()
    transport = _Transport(
        [HttpTransportResponse(status_code=302, headers={"Location": ("/final",)}, body=b"go")]
    )
    service = _service(
        tmp_path,
        clock=_Clock([0.0, 1.0, 2.0, 10.0, 10.0]),
        resolver=resolver,
        transport=transport,
    )

    with pytest.raises(HttpAcquisitionError, match="ValueError") as caught:
        service.acquire(checkpoint, target_id, _policy())

    assert caught.value.checkpoint.targets[0].status is TraversalStatus.FAILED
    assert len(transport.calls) == 1
