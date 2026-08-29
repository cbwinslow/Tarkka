"""Small filesystem durability primitives shared by storage adapters."""

from __future__ import annotations

import os
from pathlib import Path


def fsync_directory(path: Path) -> None:
    """Durably flush directory-entry changes after an atomic rename on POSIX."""
    if os.name != "posix":
        return
    # Open read-only everywhere; add O_DIRECTORY when available to require a directory path.
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
