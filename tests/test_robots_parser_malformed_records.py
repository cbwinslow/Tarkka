from __future__ import annotations

import pytest

from tarkka.domain.robots_rules import RobotsRules

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def test_invalid_user_agent_line_does_not_terminate_current_group() -> None:
    rules = RobotsRules.parse(
        """User-agent: TarkkaBot
Disallow: /blocked
User-agent: invalid/token
Disallow: /still-blocked
"""
    )

    assert rules.can_fetch("https://example.org/blocked", "TarkkaBot") is False
    assert rules.can_fetch("https://example.org/still-blocked", "TarkkaBot") is False


def test_invalid_rule_characters_are_ignored_without_losing_later_rules() -> None:
    rules = RobotsRules.parse(
        """User-agent: *
Disallow: /bad path
Disallow: /valid
"""
    )

    assert rules.can_fetch("https://example.org/bad%20path", "TarkkaBot") is True
    assert rules.can_fetch("https://example.org/valid", "TarkkaBot") is False


def test_invalid_utf8_surrogate_is_rejected_at_file_boundary() -> None:
    with pytest.raises(ValueError, match="valid UTF-8"):
        RobotsRules.parse("User-agent: *\nDisallow: /\ud800\n")
