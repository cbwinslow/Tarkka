from __future__ import annotations

import hashlib
import unicodedata

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
_MAX_PORTABLE_FILENAME_UTF8_BYTES = 240
_MAX_PORTABLE_FILENAME_UTF16_CODE_UNITS = 240


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
        or not _fits_portable_filename_limits(value)
        or any(_is_unsafe_filename_character(character) for character in value)
        or any(character in _UNSAFE_FILENAME_CHARACTERS for character in value)
    ):
        return False
    return _portable_stem(value).casefold() not in _WINDOWS_RESERVED_STEMS


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
        if _is_unsafe_filename_character(character)
        or character in _UNSAFE_FILENAME_CHARACTERS
        else character
        for character in value
    )
    normalized = unicodedata.normalize("NFC", normalized).strip().rstrip(". ")
    if normalized in {"", ".", ".."}:
        return fallback
    if _portable_stem(normalized).casefold() in _WINDOWS_RESERVED_STEMS:
        normalized = f"_{normalized}"
    if _fits_portable_filename_limits(normalized):
        return normalized
    return _shorten_filename_component(normalized, value)


def _is_unsafe_filename_character(character: str) -> bool:
    category = unicodedata.category(character)
    return (
        ord(character) < 32
        or ord(character) == 127
        or category in {"Cc", "Cf", "Cs", "Zl", "Zp"}
    )


def _fits_portable_filename_limits(value: str) -> bool:
    try:
        return (
            len(value.encode("utf-8")) <= _MAX_PORTABLE_FILENAME_UTF8_BYTES
            and len(value.encode("utf-16-le")) // 2 <= _MAX_PORTABLE_FILENAME_UTF16_CODE_UNITS
        )
    except UnicodeEncodeError:
        return False


def _portable_stem(value: str) -> str:
    return value.lstrip(".").split(".", 1)[0].rstrip(". ")


def _shorten_filename_component(normalized: str, source: str) -> str:
    stem, separator, suffix = normalized.rpartition(".")
    extension = f"{separator}{suffix}" if stem else ""
    digest = hashlib.sha256(source.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    if not _fits_portable_filename_limits(f"-{digest}{extension}"):
        extension = ""
    prefix = ""
    for character in (stem or normalized):
        candidate = f"{prefix}{character}-{digest}{extension}"
        if not _fits_portable_filename_limits(candidate):
            break
        prefix += character
    return f"{prefix}-{digest}{extension}"
