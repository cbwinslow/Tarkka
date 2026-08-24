from __future__ import annotations

from itertools import count
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from tarkka.application.http_policy_fetch import (
    HttpPolicyFetchService,
    HttpPolicyRedirectLimitError,
)
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
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

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.regression]

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
    def __init__(self, outcomes: list[HttpTransportResponse]) -> None:
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
        return self.outcomes.pop(0)


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_depth": 2,
        "max_requests": 5,
        "max_bytes": 1024,
        "max_redirects": 1,
        "max_elapsed_seconds": 60.0,
        "min_request_interval_seconds": 0.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _service(
    tmp_path: Path,
    *,
    resolver: _Resolver,
    transport: _Transport,
) -> HttpPolicyFetchService:
    ticks = count(100.0, 0.25)
    return HttpPolicyFetchService(
        resolver=resolver,
        transport=transport,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        observation_repository=JsonSourceObservationRepository(tmp_path / "observations.json"),
        checkpoint_repository=JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json"),
        finalization_repository=JsonPolicyFetchFinalizationRepository(
            tmp_path / "policy-finalizations.json"
        ),
        clock=lambda: next(ticks),
        sleeper=lambda _: None,
    )


def _checkpoint() -> TraversalCheckpoint:
    return TraversalCheckpoint(uuid4()).enqueue("https://example.org/article", depth=1)


def test_invalid_policy_uri_is_rejected_before_dns(tmp_path: Path) -> None:
    resolver = _Resolver()
    service = _service(tmp_path, resolver=resolver, transport=_Transport([]))

    with pytest.raises(ValueError, match="policy resource URI"):
        service.fetch(
            _checkpoint(),
            _policy(),
            uri="https://[broken",
            depth=1,
        )

    assert resolver.calls == []


def test_redirect_limit_has_typed_failure_and_preserves_budget(tmp_path: Path) -> None:
    resolver = _Resolver()
    transport = _Transport(
        [
            HttpTransportResponse(status_code=302, headers={"Location": ("/r1",)}),
            HttpTransportResponse(status_code=302, headers={"Location": ("/r2",)}),
        ]
    )
    service = _service(tmp_path, resolver=resolver, transport=transport)

    with pytest.raises(HttpPolicyRedirectLimitError) as exc_info:
        service.fetch(
            _checkpoint(),
            _policy(max_redirects=1),
            uri="https://example.org/robots.txt",
            depth=1,
        )

    assert exc_info.value.checkpoint.budget.requests_used == 2
    assert [call["uri"] for call in transport.calls] == [
        "https://example.org/robots.txt",
        "https://example.org/r1",
    ]
