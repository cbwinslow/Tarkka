from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


def is_safe_filename_component(value: object) -> bool:
    """Return whether a value is one non-blank filename component on POSIX and Windows."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or value in {".", ".."}
        or "\x00" in value
    ):
        return False
    return (
        PurePosixPath(value).name == value
        and PureWindowsPath(value).name == value
    )
