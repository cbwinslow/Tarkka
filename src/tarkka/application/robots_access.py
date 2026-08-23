from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from tarkka.domain.crawl_access import (
    CrawlAccessDecision,
    CrawlAccessReason,
    RobotsFetchOutcome,
    RobotsFetchResult,
)
from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy


def robots_uri_for(target_uri: str) -> str:
    """Return the canonical robots.txt URI for an HTTP(S) target authority."""
    normalized = normalize_http_uri(target_uri, field_name="crawl target URI")
    parsed = urlsplit(normalized)
    return urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))


def evaluate_robots_access(
    *,
    target_uri: str,
    user_agent: str,
    policy: ResourceAcquisitionPolicy,
    robots: RobotsFetchResult,
) -> CrawlAccessDecision:
    """Evaluate technical acquisition bounds plus an injected robots.txt result.

    Robots rules can tighten crawl eligibility and pacing but can never override Tarkka's
    technical acquisition policy. The function is deterministic and performs no network I/O.
    """
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ValueError("crawl user_agent must be non-blank")
    normalized_user_agent = user_agent.strip()
    normalized_target = normalize_http_uri(target_uri, field_name="crawl target URI")
    expected_robots_uri = robots_uri_for(normalized_target)
    if robots.robots_uri != expected_robots_uri:
        raise ValueError("robots result does not belong to the crawl target authority")

    base_interval = policy.min_request_interval_seconds
    if not policy.allows_uri(normalized_target):
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            user_agent=normalized_user_agent,
            allowed=False,
            reason=CrawlAccessReason.TECHNICAL_POLICY_DENY,
            interval=base_interval,
        )

    if robots.outcome is RobotsFetchOutcome.UNAVAILABLE:
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            user_agent=normalized_user_agent,
            allowed=True,
            reason=CrawlAccessReason.ROBOTS_UNAVAILABLE,
            interval=base_interval,
        )
    if robots.outcome is RobotsFetchOutcome.UNREACHABLE:
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            user_agent=normalized_user_agent,
            allowed=False,
            reason=CrawlAccessReason.ROBOTS_UNREACHABLE,
            interval=base_interval,
        )
    if robots.outcome is RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED:
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            user_agent=normalized_user_agent,
            allowed=False,
            reason=CrawlAccessReason.ROBOTS_REDIRECT_LIMIT,
            interval=base_interval,
        )

    parser = RobotFileParser()
    parser.set_url(robots.robots_uri)
    parser.parse((robots.content or "").splitlines())
    interval = max(base_interval, _robots_interval(parser, normalized_user_agent))
    allowed = parser.can_fetch(normalized_user_agent, normalized_target)
    return _decision(
        target_uri=normalized_target,
        robots=robots,
        user_agent=normalized_user_agent,
        allowed=allowed,
        reason=(CrawlAccessReason.ROBOTS_ALLOW if allowed else CrawlAccessReason.ROBOTS_DISALLOW),
        interval=interval,
    )


def _robots_interval(parser: RobotFileParser, user_agent: str) -> float:
    crawl_delay = parser.crawl_delay(user_agent)
    request_rate = parser.request_rate(user_agent)
    intervals = [0.0]
    if crawl_delay is not None:
        intervals.append(float(crawl_delay))
    if request_rate is not None and request_rate.requests > 0:
        intervals.append(float(request_rate.seconds) / request_rate.requests)
    return max(intervals)


def _decision(
    *,
    target_uri: str,
    robots: RobotsFetchResult,
    user_agent: str,
    allowed: bool,
    reason: CrawlAccessReason,
    interval: float,
) -> CrawlAccessDecision:
    return CrawlAccessDecision(
        target_uri=target_uri,
        robots_uri=robots.robots_uri,
        user_agent=user_agent,
        allowed=allowed,
        reason=reason,
        robots_outcome=robots.outcome,
        effective_min_request_interval_seconds=interval,
    )
