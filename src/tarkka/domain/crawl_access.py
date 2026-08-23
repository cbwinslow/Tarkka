from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from tarkka.domain.http_observations import normalize_http_uri


class RobotsFetchOutcome(StrEnum):
    """Result of acquiring a site's robots.txt through Tarkka's HTTP boundary."""

    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    UNREACHABLE = "unreachable"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"


class CrawlAccessReason(StrEnum):
    """Stable reason codes for crawl eligibility decisions."""

    TECHNICAL_POLICY_DENY = "technical_policy_deny"
    ROBOTS_ALLOW = "robots_allow"
    ROBOTS_DISALLOW = "robots_disallow"
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    ROBOTS_UNREACHABLE = "robots_unreachable"
    ROBOTS_REDIRECT_LIMIT = "robots_redirect_limit"


@dataclass(frozen=True, slots=True)
class RobotsFetchResult:
    """Injected, secret-safe result of fetching one robots.txt resource.

    The decision layer never performs network I/O itself. Callers must acquire robots.txt through
    the existing bounded and SSRF-safe HTTP path, then pass the sanitized outcome here.
    """

    robots_uri: str
    outcome: RobotsFetchOutcome
    content: str | None = None
    status_code: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "robots_uri",
            normalize_http_uri(self.robots_uri, field_name="robots URI"),
        )
        if not isinstance(self.outcome, RobotsFetchOutcome):
            raise ValueError("robots outcome must be a RobotsFetchOutcome")
        if self.status_code is not None and (
            not isinstance(self.status_code, int)
            or isinstance(self.status_code, bool)
            or not 100 <= self.status_code <= 599
        ):
            raise ValueError("robots status_code must be an HTTP status code")
        if self.outcome is RobotsFetchOutcome.SUCCESS:
            if self.content is None:
                raise ValueError("successful robots result must include content")
            if self.status_code is not None and not 200 <= self.status_code <= 299:
                raise ValueError("successful robots result must use a 2xx status code")
        elif self.content is not None:
            raise ValueError("non-successful robots result must not include content")


@dataclass(frozen=True, slots=True)
class CrawlAccessDecision:
    """Pure crawl-eligibility result suitable for provenance and orchestration."""

    target_uri: str
    robots_uri: str
    user_agent: str
    allowed: bool
    reason: CrawlAccessReason
    robots_outcome: RobotsFetchOutcome
    effective_min_request_interval_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_uri",
            normalize_http_uri(self.target_uri, field_name="crawl target URI"),
        )
        object.__setattr__(
            self,
            "robots_uri",
            normalize_http_uri(self.robots_uri, field_name="robots URI"),
        )
        if not isinstance(self.user_agent, str) or not self.user_agent.strip():
            raise ValueError("crawl user_agent must be non-blank")
        object.__setattr__(self, "user_agent", self.user_agent.strip())
        if not isinstance(self.allowed, bool):
            raise ValueError("crawl allowed must be boolean")
        if not isinstance(self.reason, CrawlAccessReason):
            raise ValueError("crawl reason must be a CrawlAccessReason")
        if not isinstance(self.robots_outcome, RobotsFetchOutcome):
            raise ValueError("robots outcome must be a RobotsFetchOutcome")
        interval = self.effective_min_request_interval_seconds
        if not isinstance(interval, (int, float)) or isinstance(interval, bool):
            raise ValueError("effective crawl interval must be numeric")
        if not math.isfinite(float(interval)) or interval < 0:
            raise ValueError("effective crawl interval must be finite and non-negative")
        object.__setattr__(
            self,
            "effective_min_request_interval_seconds",
            float(interval),
        )
