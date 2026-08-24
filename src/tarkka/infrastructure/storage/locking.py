from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

_EMPTY_LOCK_STALE_SECONDS = 10.0

@contextmanager
def exclusive_lock(
    target: Path,
    *,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Acquire a local-filesystem process lock for ``target``.

    The lock resolves symlinks and recovers lock files whose recorded PID no longer exists. It is
    intended for local filesystems; distributed/network filesystems should use a database or a
    filesystem-native distributed lock instead of relying on ``O_EXCL`` semantics.
    """
    resolved = target.expanduser().resolve()
    lock_path = resolved.with_name(f"{resolved.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _remove_stale_lock(lock_path):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_path}") from None
            time.sleep(poll_seconds)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        with suppress(FileNotFoundError):
            lock_path.unlink()


def _remove_stale_lock(lock_path: Path) -> bool:
    try:
        raw_pid = lock_path.read_text(encoding="ascii").strip()
    except (FileNotFoundError, OSError):
        return False
    if not raw_pid:
        try:
            age = time.time() - lock_path.stat().st_mtime
        except FileNotFoundError:
            return True
        if age < _EMPTY_LOCK_STALE_SECONDS:
            return False
        with suppress(FileNotFoundError):
            lock_path.unlink()
        return True
    try:
        pid = int(raw_pid)
    except ValueError:
        return False
    if _process_exists(pid):
        return False
    with suppress(FileNotFoundError):
        lock_path.unlink()
    return True


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
