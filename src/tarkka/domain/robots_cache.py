from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult

_MAX_CACHE_AGE = timedelta(hours=24)
_MAX_ROBOTS_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class RobotsCacheEntry:
    """One bounded cached robots fetch result for a canonical robots URI.

    ``expires_at`` is the normal refresh boundary. A successful entry may still be used after a
    temporary unreachable refresh only while the original fetch remains inside the hard 24-hour
    cache window. HTTP observation/artifact identifiers are retained when a response produced
    durable provenance; transport failures and redirect exhaustion may legitimately have neither.
    """

    result: RobotsFetchResult
    fetched_at: datetime
    expires_at: datetime
    source_observation_id: UUID | None = None
    artifact_sha256: str | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.result.robots_uri)
        if parsed.path != "/robots.txt" or parsed.query or parsed.fragment:
            raise ValueError("robots cache URI must be the canonical /robots.txt resource")
        if self.result.content is not None:
            try:
                content_size = len(self.result.content.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError("robots cache content must be valid UTF-8 text") from exc
            if content_size > _MAX_ROBOTS_BYTES:
                raise ValueError("robots cache content exceeds the 512 KiB limit")

        for name, value in (("fetched_at", self.fetched_at), ("expires_at", self.expires_at)):
            if not isinstance(value, datetime):
                raise ValueError(f"robots cache {name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"robots cache {name} must be timezone-aware")
        if self.expires_at <= self.fetched_at:
            raise ValueError("robots cache expiry must be after fetch time")
        if self.expires_at - self.fetched_at > _MAX_CACHE_AGE:
            raise ValueError("robots cache lifetime must not exceed 24 hours")

        if self.source_observation_id is not None and not isinstance(
            self.source_observation_id, UUID
        ):
            raise ValueError("robots cache source_observation_id must be a UUID")
        if self.artifact_sha256 is not None and (
            not isinstance(self.artifact_sha256, str)
            or len(self.artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.artifact_sha256)
        ):
            raise ValueError("robots cache artifact_sha256 must be lowercase SHA-256")
        if (self.source_observation_id is None) != (self.artifact_sha256 is None):
            raise ValueError("robots cache HTTP provenance identifiers must be supplied together")

    @property
    def robots_uri(self) -> str:
        return self.result.robots_uri

    def is_fresh(self, now: datetime) -> bool:
        """Return whether this entry may be used without a new policy fetch."""
        _require_aware_datetime(now)
        return self.fetched_at <= now < self.expires_at

    def may_reuse_after_unreachable(self, now: datetime) -> bool:
        """Return whether a stale successful copy may backstop a temporary unreachable refresh."""
        _require_aware_datetime(now)
        return (
            self.result.outcome is RobotsFetchOutcome.SUCCESS
            and self.fetched_at <= now < self.fetched_at + _MAX_CACHE_AGE
        )


def _require_aware_datetime(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("robots cache comparison time must be timezone-aware")
