from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.infrastructure.storage.json_robots_cache import (
    JsonRobotsCache,
    RobotsCacheConflictError,
)

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_ROBOTS = "https://example.org/robots.txt"
_T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _entry(
    *,
    fetched_at: datetime = _T0,
    lifetime: timedelta = timedelta(hours=1),
    content: str = "User-agent: *\nAllow: /\n",
) -> RobotsCacheEntry:
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content=content,
            status_code=200,
        ),
        fetched_at=fetched_at,
        expires_at=fetched_at + lifetime,
    )


def test_cache_round_trip_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    JsonRobotsCache(path).save(_entry())

    restored = JsonRobotsCache(path).get(_ROBOTS)

    assert restored == _entry()


def test_cache_replaces_entry_with_newer_fetch(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    cache = JsonRobotsCache(path)
    old = _entry()
    newer = _entry(
        fetched_at=_T0 + timedelta(minutes=30),
        content="User-agent: *\nDisallow: /private\n",
    )

    cache.save(old)
    cache.save(newer)

    assert cache.get(_ROBOTS) == newer


def test_cache_rejects_rollback_to_older_fetch(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")
    newer = _entry(fetched_at=_T0 + timedelta(hours=1))
    older = _entry(fetched_at=_T0)
    cache.save(newer)

    with pytest.raises(RobotsCacheConflictError, match="roll back"):
        cache.save(older)

    assert cache.get(_ROBOTS) == newer


def test_cache_rejects_conflicting_same_time_entry(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")
    cache.save(_entry())

    with pytest.raises(RobotsCacheConflictError, match="same fetch time"):
        cache.save(_entry(content="User-agent: *\nDisallow: /\n"))


def test_cache_entry_freshness_uses_half_open_expiry_window() -> None:
    entry = _entry(lifetime=timedelta(hours=1))

    assert entry.is_fresh(_T0) is True
    assert entry.is_fresh(_T0 + timedelta(minutes=59, seconds=59)) is True
    assert entry.is_fresh(_T0 + timedelta(hours=1)) is False


def test_cache_entry_rejects_lifetime_over_24_hours() -> None:
    with pytest.raises(ValueError, match="24 hours"):
        _entry(lifetime=timedelta(hours=24, seconds=1))


def test_cache_entry_rejects_noncanonical_robots_uri() -> None:
    result = RobotsFetchResult(
        robots_uri="https://example.org/policy/robots.txt",
        outcome=RobotsFetchOutcome.SUCCESS,
        content="User-agent: *\nAllow: /\n",
        status_code=200,
    )

    with pytest.raises(ValueError, match="canonical /robots.txt"):
        RobotsCacheEntry(
            result=result,
            fetched_at=_T0,
            expires_at=_T0 + timedelta(hours=1),
        )


def test_cache_entry_rejects_content_over_512_kib() -> None:
    with pytest.raises(ValueError, match="512 KiB"):
        _entry(content="#" + ("x" * (512 * 1024)))


def test_cache_fails_closed_on_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    JsonRobotsCache(path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid robots cache JSON"):
        JsonRobotsCache(path).get(_ROBOTS)


def test_cache_fails_closed_on_future_schema_without_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    cache = JsonRobotsCache(path)
    future = {"schema_version": 99, "entries": {}}
    path.write_text(json.dumps(future), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported robots cache schema"):
        cache.save(_entry())

    assert json.loads(path.read_text(encoding="utf-8")) == future


def test_cache_rejects_invalid_entry_shape(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    cache = JsonRobotsCache(path)
    payload = {"schema_version": 1, "entries": {_ROBOTS: []}}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="record must be an object"):
        cache.get(_ROBOTS)
