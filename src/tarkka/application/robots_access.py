from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from tarkka.domain.crawl_access import (
    CrawlAccessDecision,
    CrawlAccessReason,
    RobotsFetchOutcome,
    RobotsFetchResult,
)
from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.robots_rules import RobotsRules


def robots_uri_for(target_uri: str) -> str:
    """Return the canonical robots.txt URI for an HTTP(S) target authority."""
    normalized = normalize_http_uri(target_uri, field_name="crawl target URI")
    parsed = urlsplit(normalized)
    return urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))


def evaluate_robots_access(
    *,
    target_uri: str,
    product_token: str,
    policy: ResourceAcquisitionPolicy,
    robots: RobotsFetchResult,
) -> CrawlAccessDecision:
    """Evaluate technical acquisition bounds plus an injected robots.txt result.

    Robots rules can tighten crawl eligibility and pacing but can never override Tarkka's
    technical acquisition policy. The function is deterministic and performs no network I/O.
    """
    normalized_target = normalize_http_uri(target_uri, field_name="crawl target URI")
    expected_robots_uri = robots_uri_for(normalized_target)
    if robots.robots_uri != expected_robots_uri:
        raise ValueError("robots result does not belong to the crawl target authority")

    base_interval = policy.min_request_interval_seconds
    if not policy.allows_uri(target_uri):
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            product_token=product_token,
            allowed=False,
            reason=CrawlAccessReason.TECHNICAL_POLICY_DENY,
            interval=base_interval,
        )

    if robots.outcome is RobotsFetchOutcome.UNAVAILABLE:
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            product_token=product_token,
            allowed=True,
            reason=CrawlAccessReason.ROBOTS_UNAVAILABLE,
            interval=base_interval,
        )
    if robots.outcome is RobotsFetchOutcome.UNREACHABLE:
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            product_token=product_token,
            allowed=False,
            reason=CrawlAccessReason.ROBOTS_UNREACHABLE,
            interval=base_interval,
        )
    if robots.outcome is RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED:
        return _decision(
            target_uri=normalized_target,
            robots=robots,
            product_token=product_token,
            allowed=False,
            reason=CrawlAccessReason.ROBOTS_REDIRECT_LIMIT,
            interval=base_interval,
        )

    rules = RobotsRules.parse(robots.content or "")
    crawl_delay = rules.crawl_delay(product_token) or 0.0
    interval = max(base_interval, crawl_delay)
    allowed = rules.can_fetch(normalized_target, product_token)
    return _decision(
        target_uri=normalized_target,
        robots=robots,
        product_token=product_token,
        allowed=allowed,
        reason=(CrawlAccessReason.ROBOTS_ALLOW if allowed else CrawlAccessReason.ROBOTS_DISALLOW),
        interval=interval,
    )


def _decision(
    *,
    target_uri: str,
    robots: RobotsFetchResult,
    product_token: str,
    allowed: bool,
    reason: CrawlAccessReason,
    interval: float,
) -> CrawlAccessDecision:
    return CrawlAccessDecision(
        target_uri=target_uri,
        robots_uri=robots.robots_uri,
        product_token=product_token,
        allowed=allowed,
        reason=reason,
        robots_outcome=robots.outcome,
        effective_min_request_interval_seconds=interval,
    )
