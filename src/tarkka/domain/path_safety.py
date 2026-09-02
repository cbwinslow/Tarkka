from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

_WINDOWS_RESERVED_STEMS = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_UNSAFE_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')


def is_safe_filename_component(value: object) -> bool:
    """Return whether ``value`` is a portable, non-traversing filename component.

    The policy deliberately targets the intersection of POSIX and Windows filename
    rules because names cross the acquisition, temporary-materialization, and replay
    boundaries.  It rejects path syntax, control characters, Windows ADS syntax and
    device stems, plus spellings Windows silently aliases through trailing dots/spaces.
    """
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or value in {".", ".."}
        or value[-1] in {".", " "}
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in _UNSAFE_FILENAME_CHARACTERS for character in value)
    ):
        return False
    if not (
        PurePosixPath(value).name == value
        and PureWindowsPath(value).name == value
    ):
        return False
    return value.split(".", 1)[0].casefold() not in _WINDOWS_RESERVED_STEMS


def portable_filename_component(value: str, *, fallback: str = "artifact") -> str:
    """Canonicalize generated text into one safe portable filename component.

    This is for generated staging names, never canonical Artifact identity or source
    provenance. Callers retain the raw source value separately when the result differs.
    """
    if not isinstance(value, str):
        raise ValueError("filename component source must be a string")
    if not is_safe_filename_component(fallback):
        raise ValueError("filename component fallback must be safe")

    normalized = "".join(
        "_"
        if ord(character) < 32
        or ord(character) == 127
        or character in _UNSAFE_FILENAME_CHARACTERS
        else character
        for character in value
    ).strip().rstrip(". ")
    if normalized in {"", ".", ".."}:
        return fallback
    if normalized.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_STEMS:
        normalized = f"{normalized}_"
    return normalized if is_safe_filename_component(normalized) else fallback
