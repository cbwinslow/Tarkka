from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.http_acquisition import (
    HttpAcquisitionService,
    _abandon_finalization,
    _artifact_name,
    _lookup_target,
    _redirect_location,
    _target,
)
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

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000001990")
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self, addresses: tuple[str, ...] = (_PUBLIC_ADDRESS,)) -> None:
        self.addresses = addresses
        self.calls = 0

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del hostname, timeout_seconds
        self.calls += 1
        return self.addresses


class _Transport:
    def __init__(self, response: HttpTransportResponse | None = None) -> None:
        self.response = response or HttpTransportResponse(status_code=200, body=b"ok")
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


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 10,
        "max_bytes": 32,
        "max_retries": 1,
        "max_redirects": 2,
        "max_elapsed_seconds": 60.0,
        "min_request_interval_seconds": 0.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _checkpoint(uri: str = "https://example.org/start") -> tuple[TraversalCheckpoint, UUID]:
    checkpoint = TraversalCheckpoint(_CHECKPOINT_ID).enqueue(uri, depth=0)
    return checkpoint, checkpoint.targets[0].target_id


def _service(
    tmp_path: Path,
    *,
    resolver: _Resolver | None = None,
    transport: _Transport | None = None,
    clock: object = None,
    sleeper: object = None,
) -> HttpAcquisitionService:
    kwargs: dict[str, object] = {}
    if clock is not None:
        kwargs["clock"] = clock
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    return HttpAcquisitionService(
        resolver=resolver or _Resolver(),
        transport=transport or _Transport(),
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=JsonSourceObservationRepository(tmp_path / "observations.json"),
        checkpoint_repository=JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json"),
        **kwargs,  # type: ignore[arg-type]
    )


def test_acquire_rejects_request_uri_that_does_not_match_durable_target(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver()
    transport = _Transport()
    service = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(ValueError, match="normalize to the durable traversal target"):
        service.acquire(
            checkpoint,
            target_id,
            _policy(),
            request_uri="https://example.org/other",
        )

    assert resolver.calls == 0
    assert transport.calls == 0


def test_acquire_rejects_request_uri_outside_policy_before_network(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint("https://example.org/start")
    resolver = _Resolver()
    transport = _Transport()
    service = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(ValueError, match="not allowed by the acquisition policy"):
        service.acquire(
            checkpoint,
            target_id,
            _policy(allowed_domains=frozenset({"other.example"})),
        )

    assert resolver.calls == 0
    assert transport.calls == 0


def test_recover_finalization_rejects_non_finalizing_target(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()

    with pytest.raises(ValueError, match="requires a finalizing target"):
        _service(tmp_path).recover_finalization(checkpoint, target_id)


def test_request_once_rejects_empty_resolution(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    policy = _policy()
    active = checkpoint.start(target_id, policy)
    service = _service(tmp_path, resolver=_Resolver(()))

    with pytest.raises(ValueError, match="returned no addresses"):
        service._request_once(active, policy, "https://example.org/start", started_at=0.0)


def test_request_once_rejects_transport_body_larger_than_requested_cap(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    policy = _policy(max_bytes=2)
    active = checkpoint.start(target_id, policy)
    transport = _Transport(HttpTransportResponse(status_code=200, body=b"abc"))
    service = _service(tmp_path, transport=transport, clock=lambda: 0.0)

    with pytest.raises(ValueError, match="larger than its requested cap"):
        service._request_once(active, policy, "https://example.org/start", started_at=0.0)

    assert transport.calls == 1


def test_request_once_rejects_already_exceeded_byte_budget(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    policy = _policy(max_bytes=2)
    active = checkpoint.start(target_id, policy)
    over_budget = replace(active, budget=replace(active.budget, bytes_used=3))
    transport = _Transport()
    service = _service(tmp_path, transport=transport, clock=lambda: 0.0)

    with pytest.raises(ValueError, match="byte budget is already exceeded"):
        service._request_once(
            over_budget,
            policy,
            "https://example.org/start",
            started_at=0.0,
        )

    assert transport.calls == 0


def test_wait_for_followup_rejects_interval_larger_than_elapsed_budget(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    policy = _policy(min_request_interval_seconds=2.0, max_elapsed_seconds=1.0)
    active = checkpoint.start(target_id, policy)
    service = _service(tmp_path, clock=lambda: 0.0)

    with pytest.raises(ValueError, match="wait would exceed elapsed-time budget"):
        service._wait_for_followup(
            active,
            active.targets[0],
            policy,
            started_at=0.0,
        )


def test_wait_for_followup_sleeps_when_interval_is_positive(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    policy = _policy(min_request_interval_seconds=0.5)
    active = checkpoint.start(target_id, policy)
    sleeps: list[float] = []
    service = _service(tmp_path, clock=lambda: 0.0, sleeper=sleeps.append)

    service._wait_for_followup(active, active.targets[0], policy, started_at=0.0)

    assert sleeps == [0.5]


def test_remaining_elapsed_is_unbounded_when_policy_has_no_limit(tmp_path: Path) -> None:
    checkpoint, target_id = _checkpoint()
    policy = _policy(max_elapsed_seconds=None)
    active = checkpoint.start(target_id, policy)

    assert _service(tmp_path)._remaining_elapsed(active, policy, 0.0) is None


def test_elapsed_rejects_backwards_clock(tmp_path: Path) -> None:
    checkpoint, _ = _checkpoint()
    service = _service(tmp_path, clock=lambda: 9.0)

    with pytest.raises(ValueError, match="clock moved backwards"):
        service._elapsed(checkpoint, started_at=10.0)


@pytest.mark.parametrize("clock_value", [True, "1"])
def test_read_clock_rejects_non_numeric_values(tmp_path: Path, clock_value: object) -> None:
    service = _service(tmp_path, clock=lambda: clock_value)

    with pytest.raises(ValueError, match="clock must return a number"):
        service._read_clock()


@pytest.mark.parametrize("clock_value", [float("nan"), float("inf")])
def test_read_clock_rejects_non_finite_values(tmp_path: Path, clock_value: float) -> None:
    service = _service(tmp_path, clock=lambda: clock_value)

    with pytest.raises(ValueError, match="clock must return a finite value"):
        service._read_clock()


def test_lookup_target_validates_checkpoint_and_target_id() -> None:
    checkpoint, _ = _checkpoint()

    with pytest.raises(ValueError, match="checkpoint must be"):
        _lookup_target(cast(TraversalCheckpoint, object()), uuid4())
    with pytest.raises(ValueError, match="target_id must be"):
        _lookup_target(checkpoint, cast(UUID, "not-a-uuid"))
    with pytest.raises(ValueError, match="target does not exist"):
        _lookup_target(checkpoint, uuid4())


def test_target_rejects_non_queued_target() -> None:
    checkpoint, target_id = _checkpoint()
    active = checkpoint.start(target_id, _policy())

    with pytest.raises(ValueError, match="target must be queued"):
        _target(active, target_id)


def test_abandon_finalization_rejects_non_finalizing_target() -> None:
    checkpoint, target_id = _checkpoint()

    with pytest.raises(ValueError, match="only finalizing"):
        _abandon_finalization(
            checkpoint,
            target_id,
            reason="not finalizing",
            elapsed_seconds=0.0,
        )


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({}, None),
        ({"location": ("",)}, "must not be blank"),
        ({"location": ("/two words",)}, "must not contain whitespace"),
        ({"location": ("javascript:alert(1)",)}, "must use HTTP"),
        ({"location": ("http://[::1",)}, "valid URI reference"),
    ],
)
def test_redirect_location_contract(
    headers: dict[str, tuple[str, ...]],
    message: str | None,
) -> None:
    response = HttpTransportResponse(status_code=302, headers=headers)

    if message is None:
        assert _redirect_location(response) is None
    else:
        with pytest.raises(ValueError, match=message):
            _redirect_location(response)


def test_artifact_name_uses_final_path_component_or_none() -> None:
    assert _artifact_name("https://example.org/path/paper.pdf?token=x") == "paper.pdf"
    assert _artifact_name("https://example.org/") is None
