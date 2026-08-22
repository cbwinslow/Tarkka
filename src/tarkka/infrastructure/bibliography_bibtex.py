from __future__ import annotations

import re
from collections.abc import Mapping

from tarkka.domain.bibliography import BibliographyFormat, BibliographyRecord
from tarkka.infrastructure.bibliography_common import optional_text, required_text, year
from tarkka.infrastructure.bibliography_errors import BibliographyParseError

_BIBTEX_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_MONTHS = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}


def parse_bibtex(text: str) -> tuple[BibliographyRecord, ...]:
    entries, macros = _bibtex_entries(_strip_percent_comments(text))
    records: list[BibliographyRecord] = []
    for entry_type, source_key, field_text in entries:
        fields = _bibtex_fields(field_text, macros)
        title = required_text(
            _field_value(fields, "title"),
            f"BibTeX entry {source_key!r} title",
        )
        records.append(
            BibliographyRecord(
                source_format=BibliographyFormat.BIBTEX,
                source_key=source_key,
                entry_type=entry_type,
                title=_clean_bibtex_text(title),
                authors=_bibtex_authors(_field_value(fields, "author")),
                year=year(_field_value(fields, "year")),
                doi=optional_text(_field_value(fields, "doi")),
                url=optional_text(_field_value(fields, "url")),
                fields=fields,
            )
        )
    return tuple(records)


def _field_value(fields: Mapping[str, str], name: str) -> str | None:
    """Read a BibTeX field case-insensitively without rewriting native keys."""
    folded_name = name.casefold()
    return next((value for key, value in fields.items() if key.casefold() == folded_name), None)


def _strip_percent_comments(text: str) -> str:
    """Remove unescaped `%` comments outside braced or quoted field values."""
    output: list[str] = []
    brace_depth = 0
    paren_depth = 0
    quoted = False
    escaped = False
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if escaped:
            output.append(char)
            escaped = False
            cursor += 1
            continue
        if char == "\\":
            output.append(char)
            escaped = True
            cursor += 1
            continue
        if char == '"':
            output.append(char)
            quoted = not quoted
            cursor += 1
            continue
        if not quoted:
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth = max(0, paren_depth - 1)
            elif char == "%" and _is_comment_position(brace_depth, paren_depth):
                while cursor < len(text) and text[cursor] not in "\r\n":
                    cursor += 1
                continue
        output.append(char)
        cursor += 1
    return "".join(output)


def _is_comment_position(brace_depth: int, paren_depth: int) -> bool:
    """Allow comments outside values for either valid entry delimiter style."""
    in_brace_entry = brace_depth == 1 and paren_depth == 0
    in_paren_entry = paren_depth == 1 and brace_depth == 0
    return (brace_depth == 0 and paren_depth == 0) or in_brace_entry or in_paren_entry


def _bibtex_entries(text: str) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    entries: list[tuple[str, str, str]] = []
    macros = dict(_MONTHS)
    cursor = 0
    while True:
        at = text.find("@", cursor)
        if at < 0:
            break
        name_match = _BIBTEX_NAME.match(text, at + 1)
        if name_match is None:
            cursor = at + 1
            continue
        entry_type = name_match.group(0).lower()
        index = _skip_space(text, name_match.end())
        if index >= len(text) or text[index] not in "{(":
            raise BibliographyParseError(f"BibTeX @{entry_type} is missing an opening delimiter")
        opener = text[index]
        closer = "}" if opener == "{" else ")"
        body, cursor = _balanced_body(text, index + 1, opener, closer)
        if entry_type in {"comment", "preamble"}:
            continue
        if entry_type == "string":
            macro_fields = _bibtex_fields(body, macros)
            # Macro lookup is case-insensitive; ordinary field keys retain source casing.
            macros.update({key.lower(): value for key, value in macro_fields.items()})
            continue
        source_key, field_text = _split_bibtex_key(body, entry_type)
        entries.append((entry_type, source_key, field_text))
    return entries, macros


def _split_bibtex_key(body: str, entry_type: str) -> tuple[str, str]:
    comma = _top_level_delimiter(body, ",")
    if comma < 0:
        raise BibliographyParseError(f"BibTeX @{entry_type} entry has no field separator")
    key = body[:comma].strip()
    if not key:
        raise BibliographyParseError(f"BibTeX @{entry_type} entry has a blank citation key")
    return key, body[comma + 1 :]


def _bibtex_fields(text: str, macros: Mapping[str, str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    folded_keys: set[str] = set()
    cursor = 0
    while cursor < len(text):
        cursor = _skip_space_and_commas(text, cursor)
        if cursor >= len(text):
            break
        match = _BIBTEX_NAME.match(text, cursor)
        if match is None:
            raise BibliographyParseError(f"invalid BibTeX field near {text[cursor:cursor + 30]!r}")
        key = match.group(0)
        folded_key = key.casefold()
        if folded_key in folded_keys:
            raise BibliographyParseError(
                f"duplicate BibTeX field is ambiguous case-insensitively: {key!r}"
            )
        folded_keys.add(folded_key)
        cursor = _skip_space(text, match.end())
        if cursor >= len(text) or text[cursor] != "=":
            raise BibliographyParseError(f"BibTeX field {key!r} is missing '='")
        cursor = _skip_space(text, cursor + 1)
        value, cursor = _bibtex_value(text, cursor, macros)
        fields[key] = value.strip()
        cursor = _skip_space(text, cursor)
        if cursor < len(text) and text[cursor] != ",":
            raise BibliographyParseError(
                f"BibTeX field {key!r} has unexpected trailing content"
            )
    return fields


def _bibtex_value(
    text: str,
    cursor: int,
    macros: Mapping[str, str],
) -> tuple[str, int]:
    parts: list[str] = []
    while True:
        part, cursor = _bibtex_atom(text, cursor, macros)
        parts.append(part)
        cursor = _skip_space(text, cursor)
        if cursor >= len(text) or text[cursor] != "#":
            return "".join(parts), cursor
        cursor = _skip_space(text, cursor + 1)


def _bibtex_atom(
    text: str,
    cursor: int,
    macros: Mapping[str, str],
) -> tuple[str, int]:
    if cursor >= len(text):
        raise BibliographyParseError("unexpected end of BibTeX value")
    if text[cursor] == "{":
        return _balanced_body(text, cursor + 1, "{", "}")
    if text[cursor] == '"':
        return _quoted_bibtex(text, cursor + 1)
    end = cursor
    while end < len(text) and text[end] not in "#,\r\n\t ":
        end += 1
    token = text[cursor:end].strip()
    if not token:
        raise BibliographyParseError("empty BibTeX value atom")
    return macros.get(token.lower(), token), end


def _balanced_body(text: str, cursor: int, opener: str, closer: str) -> tuple[str, int]:
    start = cursor
    depth = 1
    brace_depth = 0
    quoted = False
    escaped = False
    while cursor < len(text):
        char = text[cursor]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        # Paren-delimited entries may contain parentheses inside braced/quoted values.
        elif opener == "(" and char == "{" and not quoted:
            brace_depth += 1
        elif opener == "(" and char == "}" and brace_depth and not quoted:
            brace_depth -= 1
        elif opener == "(" and char == '"' and brace_depth == 0:
            quoted = not quoted
        elif opener == "(" and (brace_depth > 0 or quoted):
            pass
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start:cursor], cursor + 1
        cursor += 1
    raise BibliographyParseError(f"unterminated BibTeX delimiter {opener!r}")


def _quoted_bibtex(text: str, cursor: int) -> tuple[str, int]:
    start = cursor
    depth = 0
    escaped = False
    while cursor < len(text):
        char = text[cursor]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        elif char == '"' and depth == 0:
            return text[start:cursor], cursor + 1
        cursor += 1
    raise BibliographyParseError("unterminated quoted BibTeX value")


def _top_level_delimiter(text: str, delimiter: str) -> int:
    brace_depth = 0
    paren_depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
            elif char == delimiter and brace_depth == 0 and paren_depth == 0:
                return index
    return -1


def _bibtex_authors(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        _clean_bibtex_text(part.strip())
        for part in re.split(r"\s+and\s+", value, flags=re.IGNORECASE)
        if part.strip()
    )


def _clean_bibtex_text(value: str) -> str:
    stripped = value.strip()
    while len(stripped) >= 2 and stripped[0] == "{" and stripped[-1] == "}":
        try:
            body, end = _balanced_body(stripped, 1, "{", "}")
        except BibliographyParseError:
            break
        if end != len(stripped):
            break
        stripped = body.strip()
    return " ".join(stripped.split())


def _skip_space(text: str, cursor: int) -> int:
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _skip_space_and_commas(text: str, cursor: int) -> int:
    while cursor < len(text) and (text[cursor].isspace() or text[cursor] == ","):
        cursor += 1
    return cursor
