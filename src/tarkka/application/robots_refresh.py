from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from tarkka.application.http_policy_fetch import (
    HttpPolicyFetchError,
    HttpPolicyFetchResult,
    HttpPolicyRedirectLimitError,
)
from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.traversal import TraversalCheckpoint
from tarkka.ports.robots_cache import RobotsCache

_SUCCESS_TTL = timedelta(hours=6)
_UNAVAILABLE_TTL = timedelta(hours=1)
_UNREACHABLE_TTL = timedelta(minutes=15)
_REDIRECT_LIMIT_TTL = timedelta(hours=1)


class PolicyResourceFetcher(Protocol):
    """Application boundary required to acquire one bounded policy resource."""

    def fetch(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        uri: str,
        depth: int,
        seconds_since_last_request: float | None = None,
    ) -> HttpPolicyFetchResult: ...


@dataclass(frozen=True, slots=True)
class RobotsRefreshResult:
    """One robots refresh attempt plus the cache entry selected for crawl decisions."""

    checkpoint: TraversalCheckpoint
    entry: RobotsCacheEntry
    refresh_entry: RobotsCacheEntry
    used_stale_success: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, TraversalCheckpoint):
            raise ValueError("robots refresh checkpoint must be a TraversalCheckpoint")
        if not isinstance(self.entry, RobotsCacheEntry):
            raise ValueError("robots refresh entry must be a RobotsCacheEntry")
        if not isinstance(self.refresh_entry, RobotsCacheEntry):
            raise ValueError("robots refresh attempt must be a RobotsCacheEntry")
        if not isinstance(self.used_stale_success, bool):
            raise ValueError("robots stale-success flag must be boolean")
        if self.entry.robots_uri != self.refresh_entry.robots_uri:
            raise ValueError("robots refresh entries must refer to the same canonical URI")
        if self.used_stale_success:
            if self.entry.result.outcome is not RobotsFetchOutcome.SUCCESS:
                raise ValueError("robots stale fallback must use a successful cached result")
            if self.refresh_entry.result.outcome is not RobotsFetchOutcome.UNREACHABLE:
                raise ValueError("robots stale fallback requires an unreachable refresh")


class RobotsRefreshService:
    """Acquire robots.txt through the bounded HTTP path and update the durable cache.

    Successful results use a six-hour normal refresh interval. A stale successful copy may
    temporarily backstop an unreachable refresh only while its original fetch is less than 24
    hours old; the failed refresh remains separately provenance-visible in ``refresh_entry`` and
    its HTTP artifact/observation remains durable through ``HttpPolicyFetchService``.
    """

    def __init__(
        self,
        *,
        policy_fetcher: PolicyResourceFetcher,
        robots_cache: RobotsCache,
    ) -> None:
        self._policy_fetcher = policy_fetcher
        self._robots_cache = robots_cache

    def refresh(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        robots_uri: str,
        depth: int,
        now: datetime,
        seconds_since_last_request: float | None = None,
    ) -> RobotsRefreshResult:
        _require_aware_datetime(now)
        previous = self._robots_cache.get(robots_uri)

        try:
            fetched = self._policy_fetcher.fetch(
                checkpoint,
                policy,
                uri=robots_uri,
                depth=depth,
                seconds_since_last_request=seconds_since_last_request,
            )
        except HttpPolicyRedirectLimitError as exc:
            refresh_entry = _failure_entry(
                robots_uri=robots_uri,
                outcome=RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED,
                fetched_at=now,
                ttl=_REDIRECT_LIMIT_TTL,
            )
            self._robots_cache.save(refresh_entry)
            return RobotsRefreshResult(
                checkpoint=exc.checkpoint,
                entry=refresh_entry,
                refresh_entry=refresh_entry,
            )
        except HttpPolicyFetchError as exc:
            refresh_entry = _failure_entry(
                robots_uri=robots_uri,
                outcome=RobotsFetchOutcome.UNREACHABLE,
                fetched_at=now,
                ttl=_UNREACHABLE_TTL,
            )
            return self._finish_unreachable(
                checkpoint=exc.checkpoint,
                previous=previous,
                refresh_entry=refresh_entry,
                now=now,
            )

        refresh_entry = _entry_from_http_fetch(fetched)
        if refresh_entry.result.outcome is RobotsFetchOutcome.UNREACHABLE:
            return self._finish_unreachable(
                checkpoint=fetched.checkpoint,
                previous=previous,
                refresh_entry=refresh_entry,
                now=now,
            )

        self._robots_cache.save(refresh_entry)
        return RobotsRefreshResult(
            checkpoint=fetched.checkpoint,
            entry=refresh_entry,
            refresh_entry=refresh_entry,
        )

    def _finish_unreachable(
        self,
        *,
        checkpoint: TraversalCheckpoint,
        previous: RobotsCacheEntry | None,
        refresh_entry: RobotsCacheEntry,
        now: datetime,
    ) -> RobotsRefreshResult:
        if previous is not None and previous.may_reuse_after_unreachable(now):
            return RobotsRefreshResult(
                checkpoint=checkpoint,
                entry=previous,
                refresh_entry=refresh_entry,
                used_stale_success=True,
            )
        self._robots_cache.save(refresh_entry)
        return RobotsRefreshResult(
            checkpoint=checkpoint,
            entry=refresh_entry,
            refresh_entry=refresh_entry,
        )


def _entry_from_http_fetch(fetched: HttpPolicyFetchResult) -> RobotsCacheEntry:
    status_code = fetched.response.status_code
    if 200 <= status_code <= 299:
        result = RobotsFetchResult(
            robots_uri=fetched.response.requested_uri,
            outcome=RobotsFetchOutcome.SUCCESS,
            content=fetched.body.decode("utf-8", errors="replace"),
            status_code=status_code,
        )
        ttl = _SUCCESS_TTL
    elif 400 <= status_code <= 499:
        result = RobotsFetchResult(
            robots_uri=fetched.response.requested_uri,
            outcome=RobotsFetchOutcome.UNAVAILABLE,
            status_code=status_code,
        )
        ttl = _UNAVAILABLE_TTL
    elif 500 <= status_code <= 599:
        result = RobotsFetchResult(
            robots_uri=fetched.response.requested_uri,
            outcome=RobotsFetchOutcome.UNREACHABLE,
            status_code=status_code,
        )
        ttl = _UNREACHABLE_TTL
    else:
        result = RobotsFetchResult(
            robots_uri=fetched.response.requested_uri,
            outcome=RobotsFetchOutcome.UNREACHABLE,
        )
        ttl = _UNREACHABLE_TTL

    fetched_at = fetched.response.observed_at
    return RobotsCacheEntry(
        result=result,
        fetched_at=fetched_at,
        expires_at=fetched_at + ttl,
        source_observation_id=fetched.observation.observation_id,
        artifact_sha256=fetched.artifact.sha256,
    )


def _failure_entry(
    *,
    robots_uri: str,
    outcome: RobotsFetchOutcome,
    fetched_at: datetime,
    ttl: timedelta,
) -> RobotsCacheEntry:
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=robots_uri,
            outcome=outcome,
        ),
        fetched_at=fetched_at,
        expires_at=fetched_at + ttl,
    )


def _require_aware_datetime(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("robots refresh time must be timezone-aware")
