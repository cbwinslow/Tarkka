from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from tarkka.domain.http_observations import normalize_http_uri

_PRODUCT_TOKEN_RE = re.compile(r"^[A-Za-z_-]+$")


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
        status_code = self.status_code
        if status_code is not None and (
            not isinstance(status_code, int)
            or isinstance(status_code, bool)
            or not 100 <= status_code <= 599
        ):
            raise ValueError("robots status_code must be an HTTP status code")

        if self.outcome is RobotsFetchOutcome.SUCCESS:
            if self.content is None:
                raise ValueError("successful robots result must include content")
            if status_code is not None and not 200 <= status_code <= 299:
                raise ValueError("successful robots result must use a 2xx status code")
            return

        if self.content is not None:
            raise ValueError("non-successful robots result must not include content")
        if (
            self.outcome is RobotsFetchOutcome.UNAVAILABLE
            and status_code is not None
            and not 400 <= status_code <= 499
        ):
            raise ValueError("unavailable robots result must use a 4xx status code")
        if (
            self.outcome is RobotsFetchOutcome.UNREACHABLE
            and status_code is not None
            and not 500 <= status_code <= 599
        ):
            raise ValueError("unreachable robots result must use a 5xx status code")
        if (
            self.outcome is RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED
            and status_code is not None
            and not 300 <= status_code <= 399
        ):
            raise ValueError("redirect-limit robots result must use a 3xx status code")


@dataclass(frozen=True, slots=True)
class CrawlAccessDecision:
    """Pure crawl-eligibility result suitable for provenance and orchestration."""

    target_uri: str
    robots_uri: str
    product_token: str
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
        if (
            not isinstance(self.product_token, str)
            or _PRODUCT_TOKEN_RE.fullmatch(self.product_token.strip()) is None
        ):
            raise ValueError(
                "crawl product_token must contain only ASCII letters, underscores, and hyphens"
            )
        object.__setattr__(self, "product_token", self.product_token.strip())
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
