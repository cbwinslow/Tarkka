from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.infrastructure.storage import json_robots_cache
from tarkka.infrastructure.storage.json_robots_cache import JsonRobotsCache

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_ROBOTS = "https://example.org/robots.txt"
_FETCHED_AT = datetime(2026, 8, 28, tzinfo=UTC)


def _entry() -> RobotsCacheEntry:
    return RobotsCacheEntry(
        result=RobotsFetchResult(
            robots_uri=_ROBOTS,
            outcome=RobotsFetchOutcome.SUCCESS,
            content="User-agent: *\nAllow: /\n",
            status_code=200,
        ),
        fetched_at=_FETCHED_AT,
        expires_at=_FETCHED_AT + timedelta(hours=1),
    )


def test_repository_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "robots"
    path.mkdir()

    with pytest.raises(ValueError, match="cache path is a directory"):
        JsonRobotsCache(path)


def test_save_rejects_invalid_runtime_value(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")

    with pytest.raises(ValueError, match="entry must be a RobotsCacheEntry"):
        cache.save(object())  # type: ignore[arg-type]


def test_repeated_identical_save_is_idempotent(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")
    entry = _entry()

    cache.save(entry)
    cache.save(entry)

    assert cache.get(_ROBOTS) == entry


def test_read_failure_preserves_cache_context_and_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")

    def fail_read(*args: object, **kwargs: object) -> str:
        raise OSError("simulated robots cache read failure")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(OSError, match="unable to read robots cache") as raised:
        cache._read()

    assert isinstance(raised.value.__cause__, OSError)


def test_read_rejects_non_object_root(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")
    cache.path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="root must be an object"):
        cache._read()


def test_read_rejects_invalid_entries_bucket(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")
    cache.path.write_text(
        json.dumps({"schema_version": 1, "entries": []}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="entries must be an object"):
        cache._read()


def test_get_rejects_malformed_object_entry(tmp_path: Path) -> None:
    cache = JsonRobotsCache(tmp_path / "robots.json")
    cache.path.write_text(
        json.dumps({"schema_version": 1, "entries": {_ROBOTS: {}}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid robots cache entry"):
        cache.get(_ROBOTS)


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json_robots_cache, "os", SimpleNamespace(name="nt"))

    json_robots_cache._fsync_directory(tmp_path)
