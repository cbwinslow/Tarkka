from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from tarkka.domain.crawl_access import RobotsFetchResult

_MAX_CACHE_AGE = timedelta(hours=24)
_MAX_ROBOTS_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class RobotsCacheEntry:
    """One bounded cached robots fetch result for a canonical robots URI."""

    result: RobotsFetchResult
    fetched_at: datetime
    expires_at: datetime

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

    @property
    def robots_uri(self) -> str:
        return self.result.robots_uri

    def is_fresh(self, now: datetime) -> bool:
        """Return whether this entry may be used without a new policy fetch."""
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("robots cache comparison time must be timezone-aware")
        return self.fetched_at <= now < self.expires_at
