"""Minimal YAML 1.1 subset loader for workspace manifests. Not a general YAML library."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class SimpleYamlError(ValueError):
    """Raised when a workspace manifest is not the supported YAML subset."""


def load_simple_yaml(text: str) -> object:
    """Load mappings, lists, and scalars from indented block YAML."""
    lines = _preprocess(text)
    if not lines:
        raise SimpleYamlError("YAML document is empty")
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise SimpleYamlError(f"unexpected content at line {lines[index][2]}")
    return value


def _preprocess(text: str) -> list[tuple[int, str, int]]:
    rows: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        leading = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in leading:
            raise SimpleYamlError(f"tabs are not allowed for indentation at line {number}")
        indent = len(raw) - len(raw.lstrip(" "))
        rows.append((indent, stripped, number))
    return rows


def _parse_block(
    lines: list[tuple[int, str, int]],
    index: int,
    indent: int,
) -> tuple[object, int]:
    if index >= len(lines):
        raise SimpleYamlError("unexpected end of YAML document")
    _, content, number = lines[index]
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    if ": " in content or content.endswith(":"):
        return _parse_mapping(lines, index, indent)
    raise SimpleYamlError(f"expected a mapping or list at line {number}")


def _parse_mapping(
    lines: list[tuple[int, str, int]],
    index: int,
    indent: int,
) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    while index < len(lines):
        current_indent, content, number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"invalid indentation at line {number}")
        if content.startswith("- "):
            raise SimpleYamlError(f"expected a mapping entry at line {number}")
        key, remainder = _split_key(content, number)
        if remainder is None:
            index += 1
            if index >= len(lines) or lines[index][0] <= indent:
                mapping[key] = {}
                continue
            nested, index = _parse_block(lines, index, lines[index][0])
            mapping[key] = nested
            continue
        mapping[key] = _parse_scalar(remainder)
        index += 1
    return mapping, index


def _parse_list(
    lines: list[tuple[int, str, int]],
    index: int,
    indent: int,
) -> tuple[list[object], int]:
    items: list[object] = []
    while index < len(lines):
        current_indent, content, number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"invalid indentation at line {number}")
        if not content.startswith("- "):
            raise SimpleYamlError(f"expected a list item at line {number}")
        remainder = content[2:]
        index += 1
        if remainder.endswith(":") or ": " in remainder:
            key, value = _split_key(remainder, number)
            item: dict[str, object] = {key: {} if value is None else _parse_scalar(value)}
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_mapping(lines, index, lines[index][0])
                if value is None:
                    item[key] = nested
                else:
                    item.update(nested)
            items.append(item)
            continue
        items.append(_parse_scalar(remainder))
    return items, index


def _split_key(content: str, number: int) -> tuple[str, str | None]:
    if content.endswith(":") and ": " not in content:
        key = content[:-1].strip()
        if not key:
            raise SimpleYamlError(f"blank mapping key at line {number}")
        return key, None
    key, value = content.split(": ", 1)
    key = key.strip()
    if not key:
        raise SimpleYamlError(f"blank mapping key at line {number}")
    return key, value


def _parse_scalar(raw: str) -> object:
    value = raw.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_flow_list(inner)]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    return value


def _split_flow_list(inner: str) -> list[str]:
    """Split an inline YAML list without treating quoted commas as separators."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            current.append(char)
            continue
        if char == ",":
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    if quote is not None:
        raise SimpleYamlError("unclosed quote in inline list")
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def require_mapping(value: object, *, what: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SimpleYamlError(f"{what} must be a mapping")
    return value


def require_sequence(value: object, *, what: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SimpleYamlError(f"{what} must be a list")
    return value
