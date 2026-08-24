from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from tarkka.application.http_policy_fetch import (
    HttpPolicyFetchError,
    HttpPolicyFetchResult,
    HttpPolicyRedirectLimitError,
)
from tarkka.application.robots_refresh import RobotsRefreshService
from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.models import Artifact
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.traversal import TraversalCheckpoint

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_NOW = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
_ROBOTS = "https://example.org/robots.txt"


@dataclass
class _Cache:
    entry: RobotsCacheEntry | None = None

    def get(self, robots_uri: str) -> RobotsCacheEntry | None:
        assert robots_uri == _ROBOTS
        return self.entry

    def save(self, entry: RobotsCacheEntry) -> None:
        self.entry = entry


class _Fetcher:
    def __init__(self, result: HttpPolicyFetchResult | Exception) -> None:
        self.result = result
        self.calls = 0

    def fetch(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        uri: str,
        depth: int,
        seconds_since_last_request: float | None = None,
    ) -> HttpPolicyFetchResult:
        del checkpoint, policy, depth, seconds_since_last_request
        assert uri == _ROBOTS
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _checkpoint() -> TraversalCheckpoint:
    return TraversalCheckpoint(uuid4())


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(allowed_domains=frozenset({"example.org"}), max_requests=10)


def _http_result(
    status_code: int,
    *,
    body: bytes = b"",
    checkpoint: TraversalCheckpoint | None = None,
) -> HttpPolicyFetchResult:
    checkpoint = checkpoint or _checkpoint()
    snapshot = HttpResponseSnapshot(
        requested_uri=_ROBOTS,
        final_uri=_ROBOTS,
        status_code=status_code,
        headers={"Content-Type": ("text/plain; charset=utf-8",)},
        observed_at=_NOW,
    )
    digest = hashlib.sha256(body).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{digest}")
    artifact = Artifact(
        artifact_id=artifact_id,
        sha256=digest,
        size_bytes=len(body),
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", digest[:2], digest),
        source_uri=_ROBOTS,
        acquired_at=_NOW,
    )
    observation = snapshot.to_source_observation(native_artifact_id=artifact_id)
    return HttpPolicyFetchResult(
        checkpoint=checkpoint,
        artifact=artifact,
        observation=observation,
        response=snapshot,
        body=body,
    )


def _stale_success(*, age: timedelta) -> RobotsCacheEntry:
    fetched_at = _NOW - age
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content="User-agent: *\nAllow: /\n",
            status_code=200,
        ),
        fetched_at=fetched_at,
        expires_at=fetched_at + timedelta(hours=6),
    )


def test_successful_refresh_maps_utf8_and_preserves_http_provenance() -> None:
    body = b"User-agent: *\nDisallow: /private\n"
    fetched = _http_result(200, body=body)
    cache = _Cache()

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(fetched),
        robots_cache=cache,
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.entry.result.outcome is RobotsFetchOutcome.SUCCESS
    assert result.entry.result.content == body.decode()
    assert result.entry.source_observation_id == fetched.observation.observation_id
    assert result.entry.artifact_sha256 == fetched.artifact.sha256
    assert result.entry.expires_at - result.entry.fetched_at == timedelta(hours=6)
    assert cache.entry == result.entry


def test_404_refresh_maps_to_unavailable() -> None:
    fetched = _http_result(404, body=b"not found")
    cache = _Cache()

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(fetched),
        robots_cache=cache,
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.entry.result.outcome is RobotsFetchOutcome.UNAVAILABLE
    assert result.entry.result.status_code == 404
    assert result.entry.result.content is None
    assert cache.entry == result.entry


def test_503_refresh_uses_stale_success_and_persists_retry_window() -> None:
    previous = _stale_success(age=timedelta(hours=7))
    fetched = _http_result(503, body=b"busy")
    cache = _Cache(previous)

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(fetched),
        robots_cache=cache,
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.used_stale_success is True
    assert result.entry.result == previous.result
    assert result.entry.fetched_at == previous.fetched_at
    assert result.entry.expires_at == _NOW + timedelta(minutes=15)
    assert result.refresh_entry.result.outcome is RobotsFetchOutcome.UNREACHABLE
    assert result.refresh_entry.source_observation_id == fetched.observation.observation_id
    assert cache.entry == result.entry
    assert cache.entry.is_fresh(_NOW + timedelta(minutes=14)) is True


def test_stale_success_retry_window_never_extends_past_original_24_hours() -> None:
    previous = _stale_success(age=timedelta(hours=23, minutes=55))
    fetched = _http_result(503, body=b"busy")

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(fetched),
        robots_cache=_Cache(previous),
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.entry.expires_at == previous.fetched_at + timedelta(hours=24)


def test_network_failure_does_not_reuse_success_older_than_24_hours() -> None:
    checkpoint = _checkpoint()
    previous = _stale_success(age=timedelta(hours=24, seconds=1))
    error = HttpPolicyFetchError("network failed", checkpoint=checkpoint)
    cache = _Cache(previous)

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(error),
        robots_cache=cache,
    ).refresh(
        checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.used_stale_success is False
    assert result.entry.result.outcome is RobotsFetchOutcome.UNREACHABLE
    assert result.entry.source_observation_id is None
    assert cache.entry == result.entry


def test_redirect_limit_is_explicit_and_never_uses_stale_success() -> None:
    checkpoint = _checkpoint()
    previous = _stale_success(age=timedelta(hours=7))
    error = HttpPolicyRedirectLimitError("redirect limit", checkpoint=checkpoint)
    cache = _Cache(previous)

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(error),
        robots_cache=cache,
    ).refresh(
        checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.used_stale_success is False
    assert result.entry.result.outcome is RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED
    assert cache.entry == result.entry


def test_oversized_success_fails_closed_without_decoding_or_stale_fallback() -> None:
    fetched = _http_result(200, body=b"x" * ((512 * 1024) + 1))
    previous = _stale_success(age=timedelta(hours=7))
    cache = _Cache(previous)

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(fetched),
        robots_cache=cache,
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.used_stale_success is False
    assert result.entry.result.outcome is RobotsFetchOutcome.UNREACHABLE
    assert result.entry.source_observation_id == fetched.observation.observation_id
    assert cache.entry == result.entry


def test_non_utf8_success_fails_closed_without_stale_fallback() -> None:
    fetched = _http_result(200, body=b"User-agent: *\n#\xff\n")
    cache = _Cache(_stale_success(age=timedelta(hours=7)))

    result = RobotsRefreshService(
        policy_fetcher=_Fetcher(fetched),
        robots_cache=cache,
    ).refresh(
        fetched.checkpoint,
        _policy(),
        robots_uri=_ROBOTS,
        depth=1,
        now=_NOW,
    )

    assert result.used_stale_success is False
    assert result.entry.result.outcome is RobotsFetchOutcome.UNREACHABLE
    assert cache.entry == result.entry
