from __future__ import annotations

from typing import Protocol

from tarkka.domain.robots_cache import RobotsCacheEntry


class RobotsCache(Protocol):
    """Durable latest-entry cache keyed by canonical robots URI."""

    def get(self, robots_uri: str) -> RobotsCacheEntry | None: ...

    def save(self, entry: RobotsCacheEntry) -> None: ...
