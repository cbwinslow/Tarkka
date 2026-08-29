"""Small filesystem durability primitives shared by storage adapters."""

from __future__ import annotations

import os
from pathlib import Path


def fsync_directory(path: Path) -> None:
    """Durably flush directory-entry changes after an atomic rename on POSIX."""
    if os.name != "posix":
        return
    # O_DIRECTORY is not available everywhere; O_RDONLY is the portable fallback.
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
