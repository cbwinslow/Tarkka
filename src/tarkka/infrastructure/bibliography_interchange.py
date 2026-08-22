from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tarkka.domain.bibliography import BibliographyFormat, BibliographyRecord

_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_DOI_URL = re.compile(r"https?://(?:dx\.)?doi\.org/(.+)", re.IGNORECASE)
_RIS_LINE = re.compile(r"^([A-Z0-9]{2})  - ?(.*)$")
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


class BibliographyParseError(ValueError):
    """Raised when a bibliography interchange file is malformed or unsupported."""


def parse_bibliography(path: Path) -> tuple[BibliographyRecord, ...]:
    """Parse one bibliography interchange file using its filename suffix."""
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    text = source.read_text(encoding="utf-8-sig")
    if suffix == ".bib":
        return parse_bibtex(text)
    if suffix == ".ris":
        return parse_ris(text)
    if suffix in {".json", ".csljson", ".csl-json"}:
        return parse_csl_json(text)
    raise BibliographyParseError(f"unsupported bibliography format: {source.name!r}")


def parse_csl_json(text: str) -> tuple[BibliographyRecord, ...]:
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BibliographyParseError(f"invalid CSL-JSON: {exc}") from exc
    items: list[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and "items" in payload:
        raw_items = payload["items"]
        if not isinstance(raw_items, list):
            raise BibliographyParseError("CSL-JSON 'items' must be an array")
        items = raw_items
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise BibliographyParseError("CSL-JSON root must be an object or array")

    records: list[BibliographyRecord] = []
    for ordinal, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise BibliographyParseError(f"CSL-JSON item {ordinal} must be an object")
        title = _required_text(raw.get("title"), f"CSL-JSON item {ordinal} title")
        source_key = _optional_text(raw.get("id")) or _stable_key("csl-json", ordinal, raw)
        entry_type = _optional_text(raw.get("type")) or "unknown"
        authors = _csl_authors(raw.get("author"))
        year = _csl_year(raw.get("issued")) or _year(raw.get("published"))
        doi = _optional_text(raw.get("DOI")) or _optional_text(raw.get("doi"))
        url = _optional_text(raw.get("URL")) or _optional_text(raw.get("url"))
        records.append(
            BibliographyRecord(
                source_format=BibliographyFormat.CSL_JSON,
                source_key=source_key,
                entry_type=entry_type,
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                url=url,
                fields=raw,
            )
        )
    return tuple(records)


def parse_ris(text: str) -> tuple[BibliographyRecord, ...]:
    raw_records = _ris_blocks(text)
    records: list[BibliographyRecord] = []
    for ordinal, fields in enumerate(raw_records):
        title = _ris_first(fields, "TI", "T1", "CT", "BT")
        if title is None:
            raise BibliographyParseError(f"RIS record {ordinal} has no title")
        entry_type = _ris_first(fields, "TY") or "unknown"
        source_key = _ris_first(fields, "ID") or _stable_key("ris", ordinal, fields)
        authors = tuple(fields.get("AU", ())) or tuple(fields.get("A1", ()))
        doi = _ris_first(fields, "DO")
        url = _ris_first(fields, "UR", "L1", "L2")
        year = _year(_ris_first(fields, "PY", "Y1", "DA"))
        records.append(
            BibliographyRecord(
                source_format=BibliographyFormat.RIS,
                source_key=source_key,
                entry_type=entry_type,
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                url=url,
                fields={key: tuple(values) for key, values in fields.items()},
            )
        )
    return tuple(records)


def parse_bibtex(text: str) -> tuple[BibliographyRecord, ...]:
    entries, macros = _bibtex_entries(text)
    records: list[BibliographyRecord] = []
    for entry_type, source_key, field_text in entries:
        fields = _bibtex_fields(field_text, macros)
        title = _required_text(fields.get("title"), f"BibTeX entry {source_key!r} title")
        doi = _optional_text(fields.get("doi"))
        url = _optional_text(fields.get("url"))
        if doi is None and url:
            match = _DOI_URL.fullmatch(url.strip())
            if match:
                doi = match.group(1)
        records.append(
            BibliographyRecord(
                source_format=BibliographyFormat.BIBTEX,
                source_key=source_key,
                entry_type=entry_type,
                title=_clean_bibtex_text(title),
                authors=_bibtex_authors(fields.get("author")),
                year=_year(fields.get("year")),
                doi=doi,
                url=url,
                fields=fields,
            )
        )
    return tuple(records)


def _ris_blocks(text: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    previous_tag: str | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r")
        match = _RIS_LINE.match(line)
        if match:
            tag, value = match.groups()
            if tag == "TY":
                if current is not None:
                    raise BibliographyParseError(
                        f"RIS line {line_number} starts a record before previous ER"
                    )
                current = {"TY": [value.strip()]}
                previous_tag = "TY"
                continue
            if current is None:
                if not line.strip():
                    continue
                raise BibliographyParseError(
                    f"RIS line {line_number} appears outside a TY/ER record"
                )
            if tag == "ER":
                records.append(current)
                current = None
                previous_tag = None
                continue
            current.setdefault(tag, []).append(value.strip())
            previous_tag = tag
            continue
        if not line.strip():
            continue
        if current is None or previous_tag is None:
            raise BibliographyParseError(f"invalid RIS line {line_number}: {line!r}")
        current[previous_tag][-1] = f"{current[previous_tag][-1]} {line.strip()}".strip()
    if current is not None:
        raise BibliographyParseError("RIS record is missing ER terminator")
    return records


def _ris_first(fields: Mapping[str, list[str]], *tags: str) -> str | None:
    for tag in tags:
        values = fields.get(tag)
        if values:
            value = values[0].strip()
            if value:
                return value
    return None


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
    cursor = 0
    while cursor < len(text):
        cursor = _skip_space_and_commas(text, cursor)
        if cursor >= len(text):
            break
        match = _BIBTEX_NAME.match(text, cursor)
        if match is None:
            raise BibliographyParseError(f"invalid BibTeX field near {text[cursor:cursor + 30]!r}")
        key = match.group(0).lower()
        cursor = _skip_space(text, match.end())
        if cursor >= len(text) or text[cursor] != "=":
            raise BibliographyParseError(f"BibTeX field {key!r} is missing '='")
        cursor = _skip_space(text, cursor + 1)
        value, cursor = _bibtex_value(text, cursor, macros)
        fields[key] = value.strip()
        cursor = _skip_space(text, cursor)
        if cursor < len(text) and text[cursor] not in ",":
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
    escaped = False
    while cursor < len(text):
        char = text[cursor]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
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


def _csl_authors(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BibliographyParseError("CSL-JSON author must be an array")
    authors: list[str] = []
    for ordinal, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise BibliographyParseError(f"CSL-JSON author {ordinal} must be an object")
        literal = _optional_text(raw.get("literal"))
        if literal:
            authors.append(literal)
            continue
        family = _optional_text(raw.get("family"))
        given = _optional_text(raw.get("given"))
        name = ", ".join(part for part in (family, given) if part)
        if name:
            authors.append(name)
    return tuple(authors)


def _csl_year(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list) or not parts[0]:
        return None
    raw_year = parts[0][0]
    if isinstance(raw_year, int):
        return raw_year
    return _year(raw_year)


def _year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 9999 else None
    match = _YEAR.search(str(value))
    return int(match.group(1)) if match else None


def _required_text(value: Any, label: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise BibliographyParseError(f"{label} must not be blank")
    return result


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _stable_key(prefix: str, ordinal: int, raw: Any) -> str:
    encoded = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"{prefix}:{ordinal}:{digest}"


def _skip_space(text: str, cursor: int) -> int:
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _skip_space_and_commas(text: str, cursor: int) -> int:
    while cursor < len(text) and (text[cursor].isspace() or text[cursor] == ","):
        cursor += 1
    return cursor
