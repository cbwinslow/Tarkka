from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.domain.crawl_access import (
    CrawlAccessDecision,
    CrawlAccessReason,
    RobotsFetchOutcome,
    RobotsFetchResult,
)
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.domain.robots_rules import RobotsRules

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_ROBOTS = "https://example.org/robots.txt"
_TARGET = "https://example.org/public/report.html"
_T0 = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _success_result(*, content: str = "User-agent: *\nAllow: /\n") -> RobotsFetchResult:
    return RobotsFetchResult(
        robots_uri=_ROBOTS,
        outcome=RobotsFetchOutcome.SUCCESS,
        content=content,
        status_code=200,
    )


def _decision() -> CrawlAccessDecision:
    return CrawlAccessDecision(
        target_uri=_TARGET,
        robots_uri=_ROBOTS,
        product_token="TarkkaBot",
        allowed=True,
        reason=CrawlAccessReason.ROBOTS_ALLOW,
        robots_outcome=RobotsFetchOutcome.SUCCESS,
        effective_min_request_interval_seconds=1.0,
    )


def _cache_entry() -> RobotsCacheEntry:
    return RobotsCacheEntry(
        result=_success_result(),
        fetched_at=_T0,
        expires_at=_T0 + timedelta(hours=1),
    )


def test_robots_fetch_result_rejects_invalid_outcome_and_status_types() -> None:
    with pytest.raises(ValueError, match="RobotsFetchOutcome"):
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=cast(RobotsFetchOutcome, "success"),
        )
    for status_code in (True, 99, 600):
        with pytest.raises(ValueError, match="HTTP status code"):
            RobotsFetchResult(
                robots_uri=_ROBOTS,
                outcome=RobotsFetchOutcome.UNAVAILABLE,
                status_code=cast(int, status_code),
            )


def test_robots_fetch_result_requires_content_only_for_success() -> None:
    with pytest.raises(ValueError, match="must include content"):
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            status_code=200,
        )
    with pytest.raises(ValueError, match="must not include content"):
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.UNAVAILABLE,
            content="unexpected",
            status_code=404,
        )

    assert (
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content="",
        ).status_code
        is None
    )
    assert (
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.UNREACHABLE,
        ).status_code
        is None
    )


@pytest.mark.parametrize("product_token", ["", "Bad Bot", "bot/1", 1])
def test_crawl_access_decision_rejects_invalid_product_tokens(product_token: object) -> None:
    with pytest.raises(ValueError, match="product_token"):
        replace(_decision(), product_token=cast(str, product_token))


def test_crawl_access_decision_rejects_invalid_enum_and_boolean_fields() -> None:
    with pytest.raises(ValueError, match="allowed must be boolean"):
        replace(_decision(), allowed=cast(bool, 1))
    with pytest.raises(ValueError, match="CrawlAccessReason"):
        replace(_decision(), reason=cast(CrawlAccessReason, "robots_allow"))
    with pytest.raises(ValueError, match="RobotsFetchOutcome"):
        replace(_decision(), robots_outcome=cast(RobotsFetchOutcome, "success"))


@pytest.mark.parametrize("interval", [True, "1", float("nan"), float("inf"), -0.1])
def test_crawl_access_decision_rejects_invalid_intervals(interval: object) -> None:
    message = "numeric" if isinstance(interval, (bool, str)) else "finite and non-negative"
    with pytest.raises(ValueError, match=message):
        replace(
            _decision(),
            effective_min_request_interval_seconds=cast(float, interval),
        )


def test_crawl_access_decision_normalizes_numeric_interval_to_float() -> None:
    decision = replace(_decision(), effective_min_request_interval_seconds=2)

    assert decision.effective_min_request_interval_seconds == 2.0
    assert isinstance(decision.effective_min_request_interval_seconds, float)


def test_robots_cache_rejects_query_fragment_and_invalid_utf8_content() -> None:
    for uri in (
        "https://example.org/robots.txt?version=1",
        "https://example.org/robots.txt#policy",
    ):
        with pytest.raises(ValueError, match="canonical /robots.txt"):
            replace(
                _cache_entry(),
                result=RobotsFetchResult(
                    robots_uri=uri,
                    outcome=RobotsFetchOutcome.SUCCESS,
                    content="",
                    status_code=200,
                ),
            )

    with pytest.raises(ValueError, match="valid UTF-8 text"):
        replace(
            _cache_entry(),
            result=_success_result(content="\ud800"),
        )


@pytest.mark.parametrize("field_name", ["fetched_at", "expires_at"])
def test_robots_cache_requires_datetime_fields(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        replace(_cache_entry(), **{field_name: cast(datetime, "now")})


def test_robots_cache_requires_timezone_aware_ordered_bounded_times() -> None:
    naive = datetime(2026, 8, 28, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_cache_entry(), fetched_at=naive)
    with pytest.raises(ValueError, match="after fetch time"):
        replace(_cache_entry(), expires_at=_T0)


def test_robots_cache_validates_provenance_identifier_types_and_hash() -> None:
    with pytest.raises(ValueError, match="source_observation_id must be a UUID"):
        replace(
            _cache_entry(),
            source_observation_id=cast(UUID, "bad"),
            artifact_sha256="a" * 64,
        )

    for artifact_sha256 in (cast(str, 1), "a" * 63, "A" * 64):
        with pytest.raises(ValueError, match="artifact_sha256"):
            replace(
                _cache_entry(),
                source_observation_id=uuid4(),
                artifact_sha256=artifact_sha256,
            )

    with pytest.raises(ValueError, match="supplied together"):
        replace(_cache_entry(), artifact_sha256="a" * 64)


def test_robots_cache_comparisons_require_aware_datetimes() -> None:
    entry = _cache_entry()
    naive = datetime(2026, 8, 28, 12, 30)

    with pytest.raises(ValueError, match="comparison time must be timezone-aware"):
        entry.is_fresh(naive)
    with pytest.raises(ValueError, match="comparison time must be timezone-aware"):
        entry.may_reuse_after_unreachable(cast(datetime, "now"))


def test_robots_rules_reject_non_text_and_invalid_utf8_content() -> None:
    with pytest.raises(ValueError, match="content must be text"):
        RobotsRules.parse(cast(str, b"User-agent: *"))
    with pytest.raises(ValueError, match="valid UTF-8 text"):
        RobotsRules.parse("\ud800")


def test_robots_rules_ignore_invalid_agents_patterns_and_crawl_delays() -> None:
    rules = RobotsRules.parse(
        """User-agent: Bad Bot!
Disallow: /ignored
User-agent: *
Disallow:
Disallow: $
Disallow: /bad path
Crawl-delay: not-a-number
Crawl-delay: -1
Crawl-delay: inf
Crawl-delay: 11111111111111111111111111111111111111111111111111111111111111111
Allow: /public
"""
    )

    assert len(rules.groups) == 1
    assert rules.groups[0].agents == ("*",)
    assert [(rule.allow, rule.pattern) for rule in rules.groups[0].rules] == [(True, "/public")]
    assert rules.can_fetch("https://example.org/ignored", "TarkkaBot") is True
    assert rules.can_fetch(_TARGET, "TarkkaBot") is True
    assert rules.crawl_delay("TarkkaBot") is None


def test_robots_rules_reject_invalid_target_and_product_token() -> None:
    rules = RobotsRules.parse("User-agent: *\nAllow: /\n")

    with pytest.raises(ValueError, match="target URI must be absolute HTTP"):
        rules.can_fetch("/relative", "TarkkaBot")
    with pytest.raises(ValueError, match="product token"):
        rules.can_fetch(_TARGET, "Bad Bot")
    with pytest.raises(ValueError, match="product token"):
        rules.crawl_delay(cast(str, None))


def test_robots_rules_canonicalize_reserved_and_malformed_percent_sequences() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /encoded%2fslash
Disallow: /literal%zzvalue
"""
    )

    assert rules.can_fetch("https://example.org/encoded%2Fslash", "TarkkaBot") is False
    assert rules.can_fetch("https://example.org/literal%zzvalue", "TarkkaBot") is False


def test_robots_pattern_matching_handles_anchored_overlap_and_wildcard_misses() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /abc*bc$
Disallow: /*middle*end
Disallow: /prefix*tail*$
"""
    )

    assert rules.can_fetch("https://example.org/abc", "TarkkaBot") is True
    assert rules.can_fetch("https://example.org/xmiddley", "TarkkaBot") is True
    assert rules.can_fetch("https://example.org/prefix-any-tail-more", "TarkkaBot") is False


def test_robots_rules_choose_strictest_delay_and_handle_empty_groups() -> None:
    rules = RobotsRules.parse(
        """User-agent: TarkkaBot
Crawl-delay: 1
Allow: /
User-agent: TarkkaBot
Crawl-delay: 3
Allow: /
User-agent: EmptyBot
"""
    )

    assert rules.crawl_delay("TarkkaBot") == 3.0
    assert rules.groups[-1].agents == ("emptybot",)
    assert rules.groups[-1].rules == ()
    assert rules.can_fetch(_TARGET, "EmptyBot") is True
