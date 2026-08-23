from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.http_acquisition import HttpAcquisitionError, HttpAcquisitionService
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.http_transport import HttpTransportResponse

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000594")
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del timeout_seconds
        assert hostname == "example.org"
        return (_PUBLIC_ADDRESS,)


class _OverflowTransport:
    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        del timeout_seconds
        assert uri == "https://example.org/large"
        assert resolved_address == _PUBLIC_ADDRESS
        assert max_response_bytes == 5
        return HttpTransportResponse(
            status_code=200,
            body=b"12345",
            limit_exceeded=True,
        )


class _RecordingObservationRepository(JsonSourceObservationRepository):
    def __init__(self, path: Path) -> None:
        self.observation_saves = 0
        self.resource_link_saves = 0
        super().__init__(path)

    def save_observation(self, observation: SourceObservation) -> None:
        self.observation_saves += 1
        super().save_observation(observation)

    def save_resource_link(self, link: ResourceLinkObservation) -> None:
        self.resource_link_saves += 1
        super().save_resource_link(link)


def test_http_overflow_persists_failure_without_observation_or_artifact(tmp_path: Path) -> None:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(
        "https://example.org/large",
        depth=0,
    )
    target_id = checkpoint.targets[0].target_id
    checkpoint_repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    observation_path = tmp_path / "observations.json"
    observation_repository = _RecordingObservationRepository(observation_path)
    artifact_root = tmp_path / "artifacts"
    service = HttpAcquisitionService(
        resolver=_Resolver(),
        transport=_OverflowTransport(),
        artifact_store=LocalArtifactStore(artifact_root),
        observation_repository=observation_repository,
        checkpoint_repository=checkpoint_repository,
        clock=lambda: 100.0,
        sleeper=lambda _: None,
    )
    policy = ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        max_depth=2,
        max_requests=10,
        max_bytes=5,
        max_retries=1,
        max_redirects=3,
        max_elapsed_seconds=60.0,
    )

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, policy)

    failed = caught.value.checkpoint
    persisted_catalog = json.loads(observation_path.read_text(encoding="utf-8"))

    assert failed.targets[0].status is TraversalStatus.FAILED
    assert failed.targets[0].bytes_acquired == 5
    assert failed.budget.bytes_used == 5
    assert checkpoint_repository.get(_CHECKPOINT_ID) == failed
    assert observation_repository.observation_saves == 0
    assert observation_repository.resource_link_saves == 0
    assert persisted_catalog["observations"] == {}
    assert persisted_catalog["resource_links"] == {}
    assert list(artifact_root.rglob("*")) == []
