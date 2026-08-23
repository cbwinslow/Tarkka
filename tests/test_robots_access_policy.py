from __future__ import annotations

import pytest

from tarkka.application.robots_access import evaluate_robots_access, robots_uri_for
from tarkka.domain.crawl_access import (
    CrawlAccessReason,
    RobotsFetchOutcome,
    RobotsFetchResult,
)
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.robots_rules import RobotsRules

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_TARGET = "https://example.org/private/report.html"
_ROBOTS = "https://example.org/robots.txt"
_TOKEN = "TarkkaBot"


def _policy(*, minimum_interval: float = 0.0) -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        min_request_interval_seconds=minimum_interval,
    )


def _success(content: str) -> RobotsFetchResult:
    return RobotsFetchResult(
        robots_uri=_ROBOTS,
        outcome=RobotsFetchOutcome.SUCCESS,
        content=content,
        status_code=200,
    )


def test_robots_uri_uses_target_scheme_and_authority_only() -> None:
    assert robots_uri_for("HTTPS://Example.Org:443/a/b?q=1#frag") == _ROBOTS
    assert robots_uri_for("http://example.org:8080/path") == (
        "http://example.org:8080/robots.txt"
    )


def test_technical_policy_denial_cannot_be_overridden_by_robots_allow() -> None:
    decision = evaluate_robots_access(
        target_uri="https://user:secret@example.org/public",
        product_token=_TOKEN,
        policy=_policy(),
        robots=_success("User-agent: *\nAllow: /\n"),
    )

    assert decision.allowed is False
    assert decision.reason is CrawlAccessReason.TECHNICAL_POLICY_DENY


def test_robots_result_must_belong_to_target_authority() -> None:
    robots = RobotsFetchResult(
        robots_uri="https://other.example/robots.txt",
        outcome=RobotsFetchOutcome.UNAVAILABLE,
        status_code=404,
    )

    with pytest.raises(ValueError, match="does not belong"):
        evaluate_robots_access(
            target_uri=_TARGET,
            product_token=_TOKEN,
            policy=_policy(),
            robots=robots,
        )


def test_unavailable_robots_allows_within_technical_policy() -> None:
    decision = evaluate_robots_access(
        target_uri=_TARGET,
        product_token=_TOKEN,
        policy=_policy(),
        robots=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.UNAVAILABLE,
            status_code=404,
        ),
    )

    assert decision.allowed is True
    assert decision.reason is CrawlAccessReason.ROBOTS_UNAVAILABLE


def test_unreachable_robots_fails_closed() -> None:
    decision = evaluate_robots_access(
        target_uri=_TARGET,
        product_token=_TOKEN,
        policy=_policy(),
        robots=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.UNREACHABLE,
            status_code=503,
        ),
    )

    assert decision.allowed is False
    assert decision.reason is CrawlAccessReason.ROBOTS_UNREACHABLE


def test_redirect_limit_is_conservatively_denied() -> None:
    decision = evaluate_robots_access(
        target_uri=_TARGET,
        product_token=_TOKEN,
        policy=_policy(),
        robots=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED,
            status_code=302,
        ),
    )

    assert decision.allowed is False
    assert decision.reason is CrawlAccessReason.ROBOTS_REDIRECT_LIMIT


def test_longest_rule_wins_over_shorter_disallow() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /private
Allow: /private/public
"""
    )

    assert rules.can_fetch("https://example.org/private/item", _TOKEN) is False
    assert rules.can_fetch("https://example.org/private/public/item", _TOKEN) is True


def test_equal_specificity_prefers_allow() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /same
Allow: /same
"""
    )

    assert rules.can_fetch("https://example.org/same/path", _TOKEN) is True


def test_matching_user_agent_groups_are_combined_case_insensitively() -> None:
    rules = RobotsRules.parse(
        """User-agent: tarkkabot
Disallow: /one

User-agent: TARKKABOT
Disallow: /two

User-agent: *
Disallow: /fallback
"""
    )

    assert rules.can_fetch("https://example.org/one", _TOKEN) is False
    assert rules.can_fetch("https://example.org/two", _TOKEN) is False
    assert rules.can_fetch("https://example.org/fallback", _TOKEN) is True


def test_wildcard_group_is_used_only_when_no_specific_group_matches() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /fallback

User-agent: OtherBot
Disallow: /other
"""
    )

    assert rules.can_fetch("https://example.org/fallback", _TOKEN) is False
    assert rules.can_fetch("https://example.org/other", _TOKEN) is True


def test_wildcard_and_end_anchor_match_without_regex_backtracking() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /*.gif$
Allow: /public/*.gif$
"""
    )

    assert rules.can_fetch("https://example.org/image.gif", _TOKEN) is False
    assert rules.can_fetch("https://example.org/image.gif?download=1", _TOKEN) is True
    assert rules.can_fetch("https://example.org/public/image.gif", _TOKEN) is True


def test_percent_encoded_unreserved_octets_compare_as_decoded_ascii() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /foo/bar/%62%61%7A\n")

    assert rules.can_fetch("https://example.org/foo/bar/baz", _TOKEN) is False


def test_unicode_patterns_and_targets_compare_in_utf8_percent_encoded_form() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /資料\n")

    assert rules.can_fetch("https://example.org/資料/report", _TOKEN) is False
    assert rules.can_fetch("https://example.org/public", _TOKEN) is True


def test_robots_txt_itself_is_implicitly_allowed() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /\n")

    assert rules.can_fetch(_ROBOTS, _TOKEN) is True


def test_parser_keeps_parseable_rules_around_malformed_lines() -> None:
    rules = RobotsRules.parse(
        """Disallow: /outside-group
User-agent: *
this is malformed
Disallow: /blocked # trailing comment
Allow: /blocked/open
"""
    )

    assert rules.can_fetch("https://example.org/outside-group", _TOKEN) is True
    assert rules.can_fetch("https://example.org/blocked/item", _TOKEN) is False
    assert rules.can_fetch("https://example.org/blocked/open/item", _TOKEN) is True


def test_crawl_delay_can_tighten_but_not_weaken_request_interval() -> None:
    robots = _success("User-agent: TarkkaBot\nCrawl-delay: 7\nAllow: /\n")

    tightened = evaluate_robots_access(
        target_uri="https://example.org/public",
        product_token=_TOKEN,
        policy=_policy(minimum_interval=2.0),
        robots=robots,
    )
    already_stricter = evaluate_robots_access(
        target_uri="https://example.org/public",
        product_token=_TOKEN,
        policy=_policy(minimum_interval=10.0),
        robots=robots,
    )

    assert tightened.effective_min_request_interval_seconds == 7.0
    assert already_stricter.effective_min_request_interval_seconds == 10.0


def test_successful_rules_drive_provenance_friendly_decision() -> None:
    decision = evaluate_robots_access(
        target_uri=_TARGET,
        product_token=_TOKEN,
        policy=_policy(),
        robots=_success("User-agent: *\nDisallow: /private\n"),
    )

    assert decision.allowed is False
    assert decision.reason is CrawlAccessReason.ROBOTS_DISALLOW
    assert decision.product_token == _TOKEN
    assert decision.robots_outcome is RobotsFetchOutcome.SUCCESS
    assert decision.target_uri == _TARGET


def test_robots_parser_rejects_content_over_512_kib() -> None:
    content = "#" + ("x" * (512 * 1024))

    with pytest.raises(ValueError, match="512 KiB"):
        RobotsRules.parse(content)


@pytest.mark.parametrize(
    ("outcome", "status_code", "message"),
    [
        (RobotsFetchOutcome.SUCCESS, 404, "2xx"),
        (RobotsFetchOutcome.UNAVAILABLE, 503, "4xx"),
        (RobotsFetchOutcome.UNREACHABLE, 404, "5xx"),
        (RobotsFetchOutcome.REDIRECT_LIMIT_EXCEEDED, 200, "3xx"),
    ],
)
def test_fetch_result_rejects_outcome_status_mismatch(
    outcome: RobotsFetchOutcome,
    status_code: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=outcome,
            content="" if outcome is RobotsFetchOutcome.SUCCESS else None,
            status_code=status_code,
        )
