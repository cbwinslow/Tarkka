from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive_lock(
    target: Path,
    *,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Cross-platform advisory lock using atomic lock-file creation."""
    lock_path = target.with_name(f"{target.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock_path}") from None
            time.sleep(poll_seconds)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
