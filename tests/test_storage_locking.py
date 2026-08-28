from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tarkka.infrastructure.storage import locking


@dataclass
class _FakeLockPath:
    raw_pid: str = ""
    read_error: OSError | None = None
    stat_error: FileNotFoundError | None = None
    mtime: float = 0.0
    unlink_error: FileNotFoundError | None = None
    unlinked: bool = False

    def read_text(self, *, encoding: str) -> str:
        assert encoding == "ascii"
        if self.read_error is not None:
            raise self.read_error
        return self.raw_pid

    def stat(self) -> Any:
        if self.stat_error is not None:
            raise self.stat_error
        return SimpleNamespace(st_mtime=self.mtime)

    def unlink(self) -> None:
        if self.unlink_error is not None:
            raise self.unlink_error
        self.unlinked = True


def test_exclusive_lock_retries_after_stale_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    calls = 0

    def fake_open(*_: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileExistsError
        return 41

    monkeypatch.setattr(locking.os, "open", fake_open)
    monkeypatch.setattr(locking, "_remove_stale_lock", lambda _: True)
    monkeypatch.setattr(locking.os, "write", lambda fd, data: len(data))
    monkeypatch.setattr(locking.os, "fsync", lambda fd: None)
    monkeypatch.setattr(locking.os, "close", lambda fd: None)

    with locking.exclusive_lock(target):
        pass

    assert calls == 2


def test_exclusive_lock_times_out_when_live_lock_never_clears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"

    def locked_open(*_: object) -> int:
        raise FileExistsError

    monkeypatch.setattr(locking.os, "open", locked_open)
    monkeypatch.setattr(locking, "_remove_stale_lock", lambda _: False)
    monkeypatch.setattr(locking.time, "monotonic", lambda: 10.0)

    with (
        pytest.raises(TimeoutError, match="timed out waiting for lock"),
        locking.exclusive_lock(target, timeout_seconds=0.0),
    ):
        pytest.fail("lock body must not run")


def test_remove_stale_lock_returns_false_when_lock_cannot_be_read() -> None:
    lock_path = _FakeLockPath(read_error=OSError("unreadable"))

    assert not locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]


def test_remove_stale_empty_lock_returns_true_when_file_disappears_during_stat() -> None:
    lock_path = _FakeLockPath(stat_error=FileNotFoundError())

    assert locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]


def test_remove_stale_empty_lock_keeps_recent_file(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = _FakeLockPath(mtime=95.0)
    monkeypatch.setattr(locking.time, "time", lambda: 100.0)

    assert not locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]
    assert not lock_path.unlinked


def test_remove_stale_empty_lock_removes_old_file(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = _FakeLockPath(mtime=80.0)
    monkeypatch.setattr(locking.time, "time", lambda: 100.0)

    assert locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]
    assert lock_path.unlinked


def test_remove_stale_empty_lock_tolerates_unlink_race(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = _FakeLockPath(mtime=80.0, unlink_error=FileNotFoundError())
    monkeypatch.setattr(locking.time, "time", lambda: 100.0)

    assert locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]


def test_remove_stale_lock_rejects_invalid_pid() -> None:
    lock_path = _FakeLockPath(raw_pid="not-a-pid")

    assert not locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]


def test_remove_stale_lock_keeps_live_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = _FakeLockPath(raw_pid="123")
    monkeypatch.setattr(locking, "_process_exists", lambda pid: True)

    assert not locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]
    assert not lock_path.unlinked


def test_remove_stale_lock_removes_dead_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = _FakeLockPath(raw_pid="123")
    monkeypatch.setattr(locking, "_process_exists", lambda pid: False)

    assert locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]
    assert lock_path.unlinked


def test_remove_stale_dead_pid_tolerates_unlink_race(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = _FakeLockPath(raw_pid="123", unlink_error=FileNotFoundError())
    monkeypatch.setattr(locking, "_process_exists", lambda pid: False)

    assert locking._remove_stale_lock(lock_path)  # type: ignore[arg-type]


def test_process_exists_rejects_non_positive_pid() -> None:
    assert not locking._process_exists(0)
    assert not locking._process_exists(-1)


def test_process_exists_returns_false_for_missing_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_process(pid: int, signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(locking.os, "kill", missing_process)

    assert not locking._process_exists(123)


def test_process_exists_returns_true_when_permission_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def inaccessible_process(pid: int, signal: int) -> None:
        raise PermissionError

    monkeypatch.setattr(locking.os, "kill", inaccessible_process)

    assert locking._process_exists(123)


def test_process_exists_returns_true_when_signal_zero_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def existing_process(pid: int, signal: int) -> None:
        calls.append((pid, signal))

    monkeypatch.setattr(locking.os, "kill", existing_process)

    assert locking._process_exists(123)
    assert calls == [(123, 0)]
