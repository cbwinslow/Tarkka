from __future__ import annotations

from typing import cast

import pytest

from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.robots_rules import RobotsRules

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_ROBOTS = "https://example.org/robots.txt"
_TARGET = "https://example.org/public/report.html"
_TOKEN = "TarkkaBot"


@pytest.mark.parametrize("content", [b"User-agent: *", 1])
def test_successful_robots_fetch_result_requires_text_content(content: object) -> None:
    with pytest.raises(ValueError, match="content must be text"):
        RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content=cast(str, content),
            status_code=200,
        )


def test_empty_or_malformed_robots_content_produces_no_groups() -> None:
    rules = RobotsRules.parse("# comment only\nmalformed line without colon\n")

    assert rules.groups == ()
    assert rules.can_fetch(_TARGET, _TOKEN) is True


def test_unknown_directive_inside_active_group_is_ignored() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Sitemap: https://example.org/sitemap.xml
Allow: /public
"""
    )

    assert rules.can_fetch(_TARGET, _TOKEN) is True


def test_leading_wildcard_pattern_matches_without_literal_prefix() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: *private$
"""
    )

    assert rules.can_fetch("https://example.org/reports/private", _TOKEN) is False
    assert rules.can_fetch("https://example.org/reports/public", _TOKEN) is True
