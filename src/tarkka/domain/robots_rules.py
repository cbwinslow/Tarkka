from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

_MAX_ROBOTS_BYTES = 512 * 1024
_PRODUCT_TOKEN_RE = re.compile(r"^[A-Za-z_-]+$")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_HEX = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True, slots=True)
class RobotsRule:
    allow: bool
    pattern: str

    @property
    def specificity(self) -> int:
        """Return the number of non-wildcard pattern octets used for precedence."""
        body = self.pattern[:-1] if self.pattern.endswith("$") else self.pattern
        body = body.replace("*", "")
        return len(body.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class RobotsGroup:
    agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...]
    crawl_delay_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class RobotsRules:
    """Bounded robots.txt rules with RFC 9309 core matching behavior.

    `crawl-delay` is parsed as a conservative extension; it is not part of RFC 9309.
    """

    groups: tuple[RobotsGroup, ...]

    @classmethod
    def parse(cls, content: str) -> RobotsRules:
        if not isinstance(content, str):
            raise ValueError("robots content must be text")
        try:
            content_bytes = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("robots content must be valid UTF-8 text") from exc
        if len(content_bytes) > _MAX_ROBOTS_BYTES:
            raise ValueError("robots content exceeds the 512 KiB parsing limit")

        groups: list[RobotsGroup] = []
        agents: list[str] = []
        rules: list[RobotsRule] = []
        crawl_delays: list[float] = []
        rules_started = False

        def finish_group() -> None:
            nonlocal agents, rules, crawl_delays, rules_started
            if agents:
                groups.append(
                    RobotsGroup(
                        agents=tuple(agents),
                        rules=tuple(rules),
                        crawl_delay_seconds=max(crawl_delays) if crawl_delays else None,
                    )
                )
            agents = []
            rules = []
            crawl_delays = []
            rules_started = False

        for raw_line in content.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            raw_key, raw_value = line.split(":", 1)
            key = raw_key.strip().lower()
            value = raw_value.strip()

            if key == "user-agent":
                valid_agent = value == "*" or _PRODUCT_TOKEN_RE.fullmatch(value) is not None
                if not valid_agent:
                    continue
                if rules_started:
                    finish_group()
                agents.append(value.lower())
                continue

            if not agents:
                continue

            if key in {"allow", "disallow"}:
                rules_started = True
                if not value:
                    continue
                try:
                    pattern = _canonicalize_rule_pattern(value)
                except ValueError:
                    continue
                rules.append(RobotsRule(allow=key == "allow", pattern=pattern))
                continue

            if key == "crawl-delay":
                delay = _parse_crawl_delay(value)
                if delay is not None:
                    crawl_delays.append(delay)

        finish_group()
        return cls(groups=tuple(groups))

    def can_fetch(self, target_uri: str, product_token: str) -> bool:
        """Return whether the most-specific applicable rule permits the target URI."""
        token = _normalize_product_token(product_token)
        parsed = urlsplit(target_uri)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("robots target URI must be absolute HTTP(S)")
        if parsed.path == "/robots.txt" and not parsed.query:
            return True

        target = _canonicalize_uri_path_query(parsed.path or "/", parsed.query)
        matches = [
            rule
            for group in self._applicable_groups(token)
            for rule in group.rules
            if _pattern_matches(rule.pattern, target)
        ]
        if not matches:
            return True
        most_specific = max(rule.specificity for rule in matches)
        equally_specific = [rule for rule in matches if rule.specificity == most_specific]
        return any(rule.allow for rule in equally_specific)

    def crawl_delay(self, product_token: str) -> float | None:
        """Return the strictest applicable Crawl-delay extension value, when present."""
        token = _normalize_product_token(product_token)
        delays = [
            group.crawl_delay_seconds
            for group in self._applicable_groups(token)
            if group.crawl_delay_seconds is not None
        ]
        return max(delays) if delays else None

    def _applicable_groups(self, product_token: str) -> tuple[RobotsGroup, ...]:
        exact = tuple(group for group in self.groups if product_token in group.agents)
        if exact:
            return exact
        return tuple(group for group in self.groups if "*" in group.agents)


def _normalize_product_token(value: str) -> str:
    if not isinstance(value, str) or _PRODUCT_TOKEN_RE.fullmatch(value.strip()) is None:
        raise ValueError(
            "robots product token must contain only ASCII letters, underscores, and hyphens"
        )
    return value.strip().lower()


def _parse_crawl_delay(value: str) -> float | None:
    if len(value) > 64:
        return None
    try:
        delay = float(value)
    except ValueError:
        return None
    if not math.isfinite(delay) or delay < 0:
        return None
    return delay


def _canonicalize_rule_pattern(value: str) -> str:
    anchored = value.endswith("$")
    body = value[:-1] if anchored else value
    if not body:
        raise ValueError("robots rule pattern must not be empty")
    if any(ord(character) < 0x21 or character == "#" for character in body):
        raise ValueError("robots rule pattern contains invalid characters")
    canonical = _canonicalize_component(body, preserve_wildcard=True)
    return canonical + ("$" if anchored else "")


def _canonicalize_uri_path_query(path: str, query: str) -> str:
    value = path + (f"?{query}" if query else "")
    return _canonicalize_component(value, preserve_wildcard=False)


def _canonicalize_component(value: str, *, preserve_wildcard: bool) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if preserve_wildcard and character == "*":
            result.append("*")
            index += 1
            continue
        if character == "%" and index + 2 < len(value):
            pair = value[index + 1 : index + 3]
            if all(item in _HEX for item in pair):
                decoded = chr(int(pair, 16))
                if decoded in _UNRESERVED:
                    result.append(decoded)
                else:
                    result.append(f"%{pair.upper()}")
                index += 3
                continue
        if ord(character) > 127:
            result.append(quote(character, safe=""))
        else:
            result.append(character)
        index += 1
    return "".join(result)


def _pattern_matches(pattern: str, target: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    parts = body.split("*")
    position = 0
    part_index = 0

    if not body.startswith("*"):
        first = parts[0]
        if not target.startswith(first):
            return False
        position = len(first)
        part_index = 1

    remaining = parts[part_index:]
    for index, part in enumerate(remaining):
        if not part:
            continue
        is_last = index == len(remaining) - 1
        if anchored and is_last and not body.endswith("*"):
            if not target.endswith(part):
                return False
            return target.rfind(part) >= position
        found = target.find(part, position)
        if found < 0:
            return False
        position = found + len(part)

    return not anchored or body.endswith("*") or position == len(target)
