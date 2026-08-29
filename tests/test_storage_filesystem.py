from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import tarkka.infrastructure.storage.filesystem as filesystem
from tarkka.infrastructure.storage.filesystem import fsync_directory

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(filesystem, "os", SimpleNamespace(name="nt"))

    fsync_directory(tmp_path)


def test_fsync_directory_uses_directory_flag_and_closes_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    def open_directory(path: Path, flags: int) -> int:
        calls.append(("open", (path, flags)))
        return 17

    def sync(descriptor: int) -> None:
        calls.append(("fsync", descriptor))

    def close(descriptor: int) -> None:
        calls.append(("close", descriptor))

    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=1,
        O_DIRECTORY=4,
        open=open_directory,
        fsync=sync,
        close=close,
    )
    monkeypatch.setattr(filesystem, "os", fake_os)

    fsync_directory(tmp_path)

    assert calls == [
        ("open", (tmp_path, 5)),
        ("fsync", 17),
        ("close", 17),
    ]


def test_fsync_directory_uses_readonly_fallback_and_closes_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []

    def fail_sync(descriptor: int) -> None:
        assert descriptor == 23
        raise OSError("injected fsync failure")

    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=2,
        open=lambda path, flags: 23 if (path, flags) == (tmp_path, 2) else -1,
        fsync=fail_sync,
        close=closed.append,
    )
    monkeypatch.setattr(filesystem, "os", fake_os)

    with pytest.raises(OSError, match="injected fsync failure"):
        fsync_directory(tmp_path)

    assert closed == [23]
