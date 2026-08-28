from __future__ import annotations

import re
from collections.abc import Mapping

from tarkka.domain.bibliography import BibliographyFormat, BibliographyRecord
from tarkka.infrastructure.bibliography_common import stable_key, year
from tarkka.infrastructure.bibliography_doi import normalize_doi_identity
from tarkka.infrastructure.bibliography_errors import BibliographyParseError

_RIS_LINE = re.compile(r"^([A-Z0-9]{2})[ \t]+-[ \t]?(.*)$")


def parse_ris(text: str) -> tuple[BibliographyRecord, ...]:
    raw_records = _ris_blocks(text)
    records: list[BibliographyRecord] = []
    for ordinal, fields in enumerate(raw_records):
        title = _ris_first(fields, "TI", "T1", "CT", "BT")
        if title is None:
            raise BibliographyParseError(f"RIS record {ordinal} has no title")
        entry_type = _ris_first(fields, "TY") or "unknown"
        source_key = _ris_first(fields, "ID") or stable_key("ris", ordinal, fields)
        raw_authors = fields.get("AU", ()) or fields.get("A1", ())
        authors = tuple(_normalize_value(value) for value in raw_authors if value.strip())
        url = _ris_first(fields, "UR", "L1", "L2")
        doi = normalize_doi_identity(
            label=f"RIS record {source_key!r}",
            explicit_doi=_ris_first(fields, "DO"),
            url=url,
        )
        records.append(
            BibliographyRecord(
                source_format=BibliographyFormat.RIS,
                source_key=source_key,
                entry_type=entry_type,
                title=title,
                authors=authors,
                year=year(_ris_first(fields, "PY", "Y1", "DA")),
                doi=doi,
                url=url,
                fields={key: tuple(values) for key, values in fields.items()},
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
                current = {"TY": [value]}
                previous_tag = "TY"
                continue
            if current is None:
                raise BibliographyParseError(
                    f"RIS line {line_number} appears outside a TY/ER record"
                )
            if tag == "ER":
                records.append(current)
                current = None
                previous_tag = None
                continue
            current.setdefault(tag, []).append(value)
            previous_tag = tag
            continue
        if not line.strip():
            continue
        if current is None or previous_tag is None:
            raise BibliographyParseError(f"invalid RIS line {line_number}: {line!r}")
        current[previous_tag][-1] += f"\n{line}"
    if current is not None:
        raise BibliographyParseError("RIS record is missing ER terminator")
    return records


def _ris_first(fields: Mapping[str, list[str]], *tags: str) -> str | None:
    for tag in tags:
        values = fields.get(tag)
        if values:
            value = _normalize_value(values[0])
            if value:
                return value
    return None


def _normalize_value(value: str) -> str:
    return " ".join(value.split())
