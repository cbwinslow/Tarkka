from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from tarkka.application.http_acquisition import (
    HttpAcquisitionCheckpointError,
    HttpAcquisitionError,
    HttpAcquisitionService,
)
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

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000550")
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self, values: dict[str, tuple[str, ...]]) -> None:
        self.values = values
        self.calls: list[str] = []

    def resolve(self, hostname: str) -> tuple[str, ...]:
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


class _FailingCheckpointRepository:
    def __init__(self) -> None:
        self.calls = 0

    def save(self, checkpoint: TraversalCheckpoint) -> None:
        del checkpoint
        self.calls += 1
        raise OSError("checkpoint disk unavailable")

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None:
        del checkpoint_id
        return None


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 10,
        "max_bytes": 1024,
        "max_retries": 1,
        "max_redirects": 3,
        "max_elapsed_seconds": 60.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _checkpoint(uri: str) -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(uri, depth=0)
    return checkpoint, checkpoint.targets[0].target_id


def _service(
    tmp_path: Path,
    *,
    resolver: _Resolver,
    transport: _Transport,
) -> tuple[
    HttpAcquisitionService,
    JsonTraversalCheckpointRepository,
    JsonSourceObservationRepository,
    LocalArtifactStore,
]:
    checkpoints = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")
    observations = JsonSourceObservationRepository(tmp_path / "observations.json")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    service = HttpAcquisitionService(
        resolver=resolver,
        transport=transport,
        artifact_store=artifacts,
        observation_repository=observations,
        checkpoint_repository=checkpoints,
        clock=lambda: 100.0,
        sleeper=lambda _: None,
    )
    return service, checkpoints, observations, artifacts


def test_acquires_artifact_and_persists_only_sanitized_http_provenance(tmp_path: Path) -> None:
    raw_uri = "https://example.org/paper.pdf?token=supersecret"
    checkpoint, target_id = _checkpoint(raw_uri)
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=200,
                headers={
                    "Content-Type": ("application/pdf",),
                    "Set-Cookie": ("session=private",),
                },
                body=b"%PDF-test",
            )
        ]
    )
    service, checkpoints, observations, artifacts = _service(
        tmp_path,
        resolver=resolver,
        transport=transport,
    )

    result = service.acquire(
        checkpoint,
        target_id,
        _policy(),
        request_uri=raw_uri,
    )

    assert result.checkpoint.targets[0].status is TraversalStatus.COMPLETED
    assert result.checkpoint.budget.requests_used == 1
    assert result.checkpoint.budget.bytes_used == len(b"%PDF-test")
    assert result.artifact.source_uri == (
        "https://example.org/paper.pdf?token=%5BREDACTED%5D"
    )
    assert result.artifact.original_name == "paper.pdf"
    assert result.artifact.media_type == "application/pdf"
    assert artifacts.read_bytes(result.artifact) == b"%PDF-test"
    assert result.response.headers.get("set-cookie") is None
    assert result.observation.metadata["requested_uri"] == result.artifact.source_uri
    assert observations.get_observation(result.observation.observation_id) == result.observation
    assert checkpoints.get(_CHECKPOINT_ID) == result.checkpoint
    assert transport.calls[0]["uri"] == raw_uri
    assert transport.calls[0]["resolved_address"] == _PUBLIC_ADDRESS
    assert transport.calls[0]["timeout_seconds"] == 60.0
    assert "supersecret" not in (tmp_path / "checkpoints.json").read_text()
    assert "supersecret" not in (tmp_path / "observations.json").read_text()


def test_redirects_are_revalidated_re_resolved_and_charged_per_hop(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=302,
                headers={"Location": ("/final",)},
                body=b"go",
            ),
            HttpTransportResponse(
                status_code=200,
                headers={"Content-Type": ("text/plain; charset=utf-8",)},
                body=b"done",
            ),
        ]
    )
    service, _, _, artifacts = _service(tmp_path, resolver=resolver, transport=transport)

    result = service.acquire(checkpoint, target_id, _policy())

    assert resolver.calls == ["example.org", "example.org"]
    assert [call["uri"] for call in transport.calls] == [
        "https://example.org/start",
        "https://example.org/final",
    ]
    assert transport.calls[1]["max_response_bytes"] == 1022
    assert transport.calls[0]["timeout_seconds"] == 60.0
    assert transport.calls[1]["timeout_seconds"] == 60.0
    assert result.response.redirect_chain == ("https://example.org/final",)
    assert result.response.final_uri == "https://example.org/final"
    assert result.checkpoint.budget.requests_used == 2
    assert result.checkpoint.budget.bytes_used == 6
    assert result.checkpoint.targets[0].bytes_acquired == 6
    assert artifacts.read_bytes(result.artifact) == b"done"


def test_multiple_location_headers_fail_closed_without_followup_request(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=302,
                headers={"Location": ("/first", "/second")},
                body=b"go",
            )
        ]
    )
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy())

    assert resolver.calls == ["example.org"]
    assert len(transport.calls) == 1
    assert caught.value.checkpoint.budget.requests_used == 1
    assert caught.value.checkpoint.budget.bytes_used == 2
    assert caught.value.checkpoint.targets[0].status is TraversalStatus.FAILED


def test_redirect_location_rejects_control_characters(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=302,
                headers={"Location": ("/first\tsecond",)},
                body=b"go",
            )
        ]
    )
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpAcquisitionError):
        service.acquire(checkpoint, target_id, _policy())

    assert len(transport.calls) == 1


def test_disallowed_dns_addresses_fail_before_transport_connection(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/private")
    resolver = _Resolver({"example.org": ("127.0.0.1", "169.254.1.2")})
    transport = _Transport([])
    service, checkpoints, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy())

    failed = caught.value.checkpoint
    assert transport.calls == []
    assert failed.targets[0].status is TraversalStatus.FAILED
    assert failed.targets[0].last_error == "http acquisition failed: ValueError"
    assert failed.budget.requests_used == 1
    assert checkpoints.get(_CHECKPOINT_ID) == failed


def test_disallowed_redirect_is_not_resolved_or_requested(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=302,
                headers={"location": ("https://evil.test/secret",)},
                body=b"r",
            )
        ]
    )
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy())

    failed = caught.value.checkpoint
    assert resolver.calls == ["example.org"]
    assert len(transport.calls) == 1
    assert failed.budget.requests_used == 1
    assert failed.budget.bytes_used == 1
    assert failed.targets[0].bytes_acquired == 1


def test_redirect_limit_fails_after_accounting_first_response(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            HttpTransportResponse(
                status_code=302,
                headers={"location": ("/next",)},
                body=b"redirect",
            )
        ]
    )
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy(max_redirects=0))

    failed = caught.value.checkpoint
    assert failed.budget.requests_used == 1
    assert failed.budget.bytes_used == len(b"redirect")
    assert len(transport.calls) == 1


def test_transport_overflow_is_charged_then_failed_without_artifact(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/large")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [HttpTransportResponse(status_code=200, body=b"12345", limit_exceeded=True)]
    )
    service, checkpoints, observations, _ = _service(
        tmp_path,
        resolver=resolver,
        transport=transport,
    )

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy(max_bytes=5))

    failed = caught.value.checkpoint
    assert transport.calls[0]["max_response_bytes"] == 5
    assert failed.budget.bytes_used == 5
    assert failed.targets[0].bytes_acquired == 5
    assert failed.targets[0].status is TraversalStatus.FAILED
    assert checkpoints.get(_CHECKPOINT_ID) == failed
    assert observations.list_resource_links(UUID(int=0)) == ()
    assert list((tmp_path / "artifacts").rglob("*")) == []


def test_transport_exception_text_is_not_persisted_in_checkpoint(tmp_path: Path) -> None:
    raw_uri = "https://example.org/data?token=supersecret"
    checkpoint, target_id = _checkpoint(raw_uri)
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport([RuntimeError(f"network failed for {raw_uri}")])
    service, _, _, _ = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpAcquisitionError) as caught:
        service.acquire(checkpoint, target_id, _policy(), request_uri=raw_uri)

    assert caught.value.checkpoint.targets[0].last_error == (
        "http acquisition failed: RuntimeError"
    )
    assert "supersecret" not in (tmp_path / "checkpoints.json").read_text()


def test_checkpoint_failure_prevents_dns_and_network_activity(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/paper")
    resolver = _Resolver({"example.org": (_PUBLIC_ADDRESS,)})
    transport = _Transport([HttpTransportResponse(status_code=200, body=b"unused")])
    service = HttpAcquisitionService(
        resolver=resolver,
        transport=transport,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=JsonSourceObservationRepository(tmp_path / "observations.json"),
        checkpoint_repository=_FailingCheckpointRepository(),
        clock=lambda: 1.0,
        sleeper=lambda _: None,
    )

    with pytest.raises(HttpAcquisitionCheckpointError):
        service.acquire(checkpoint, target_id, _policy())

    assert resolver.calls == []
    assert transport.calls == []


def test_max_redirects_requires_non_negative_integer() -> None:
    with pytest.raises(ValueError, match="max_redirects"):
        _policy(max_redirects=-1)
    with pytest.raises(ValueError, match="max_redirects"):
        _policy(max_redirects=True)
