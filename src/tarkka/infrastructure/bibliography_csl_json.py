from __future__ import annotations

import json
from typing import Any

from tarkka.domain.bibliography import BibliographyFormat, BibliographyRecord
from tarkka.infrastructure.bibliography_common import optional_text, required_text, stable_key, year
from tarkka.infrastructure.bibliography_errors import BibliographyParseError


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
        title = required_text(raw.get("title"), f"CSL-JSON item {ordinal} title")
        source_key = optional_text(raw.get("id")) or stable_key("csl-json", ordinal, raw)
        entry_type = required_text(raw.get("type"), f"CSL-JSON item {ordinal} type")
        authors = _csl_authors(raw.get("author"))
        issued_year = _csl_year(raw.get("issued")) or year(raw.get("published"))
        doi = optional_text(raw.get("DOI")) or optional_text(raw.get("doi"))
        url = optional_text(raw.get("URL")) or optional_text(raw.get("url"))
        records.append(
            BibliographyRecord(
                source_format=BibliographyFormat.CSL_JSON,
                source_key=source_key,
                entry_type=entry_type,
                title=title,
                authors=authors,
                year=issued_year,
                doi=doi,
                url=url,
                fields=raw,
            )
        )
    return tuple(records)


def _csl_authors(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BibliographyParseError("CSL-JSON author must be an array")
    authors: list[str] = []
    for ordinal, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise BibliographyParseError(f"CSL-JSON author {ordinal} must be an object")
        literal = optional_text(raw.get("literal"))
        if literal:
            authors.append(literal)
            continue
        family = optional_text(raw.get("family"))
        given = optional_text(raw.get("given"))
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
    return year(parts[0][0])
