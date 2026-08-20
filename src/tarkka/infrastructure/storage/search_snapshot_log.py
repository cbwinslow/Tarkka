from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from tarkka.domain.discovery import (
    DiscoveryRecord,
    ProviderMode,
    ResearchQuery,
    SearchSnapshot,
)
from tarkka.infrastructure.storage.locking import exclusive_lock


class SnapshotDataError(RuntimeError):
    """Raised when persisted SearchSnapshot data is malformed or inconsistent."""


class JsonlSearchSnapshotLog:
    """Append-only durable local log of scholarly discovery snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, snapshot: SearchSnapshot) -> None:
        payload = {
            "snapshot_id": str(snapshot.snapshot_id),
            "created_at": snapshot.created_at.isoformat(),
            "query": _query_to_dict(snapshot.query),
            "providers_used": list(snapshot.providers_used),
            "next_cursors": dict(snapshot.next_cursors),
            "records": [_record_to_dict(record) for record in snapshot.records],
        }
        line = json.dumps(payload, sort_keys=True) + "\n"
        with exclusive_lock(self.path), self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def get(self, snapshot_id: UUID) -> SearchSnapshot | None:
        if not self.path.exists():
            return None
        try:
            with exclusive_lock(self.path), self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise SnapshotDataError(
                            f"invalid JSON in Tarkka snapshot log {self.path} at line {line_number}"
                        ) from exc
                    if not isinstance(raw, dict):
                        raise SnapshotDataError(
                            f"invalid snapshot record at line {line_number}: expected object"
                        )
                    if raw.get("snapshot_id") == str(snapshot_id):
                        try:
                            return _snapshot_from_dict(raw)
                        except (KeyError, TypeError, ValueError) as exc:
                            raise SnapshotDataError(
                                f"invalid snapshot {snapshot_id} in {self.path}: {exc}"
                            ) from exc
        except OSError as exc:
            message = f"unable to read Tarkka search snapshots {self.path}: {exc}"
            raise RuntimeError(message) from exc
        return None


def _query_to_dict(query: ResearchQuery) -> dict[str, Any]:
    return {
        "text": query.text,
        "limit": query.limit,
        "cursor": query.cursor,
        "cursors": dict(query.cursors),
        "mode": query.mode.value,
        "providers": list(query.providers),
        "require_open_access": query.require_open_access,
        "year_from": query.year_from,
        "year_to": query.year_to,
    }


def _query_from_dict(raw: dict[str, Any]) -> ResearchQuery:
    mode_value = _optional_str(raw, "mode")
    if mode_value is None:
        mode_value = ProviderMode.AUTO.value
    elif not mode_value:
        raise TypeError("mode must not be an empty string")
    return ResearchQuery(
        text=_required_str(raw, "text"),
        limit=_int_with_default(raw, "limit", 25),
        cursor=_optional_str(raw, "cursor"),
        cursors=_string_mapping(raw.get("cursors", {}), "query.cursors"),
        mode=ProviderMode(mode_value),
        providers=_string_tuple(raw.get("providers", []), "query.providers"),
        require_open_access=_optional_bool(raw, "require_open_access", False),
        year_from=_optional_int(raw, "year_from", None),
        year_to=_optional_int(raw, "year_to", None),
    )


def _record_to_dict(record: DiscoveryRecord) -> dict[str, Any]:
    return {
        "provider": record.provider,
        "provider_id": record.provider_id,
        "title": record.title,
        "year": record.year,
        "doi": record.doi,
        "abstract": record.abstract,
        "landing_page_url": record.landing_page_url,
        "open_access_url": record.open_access_url,
        "cited_by_count": record.cited_by_count,
        "external_ids": dict(record.external_ids),
        "metadata": dict(record.metadata),
    }


def _record_from_dict(raw: dict[str, Any]) -> DiscoveryRecord:
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TypeError("record.metadata must be an object")
    return DiscoveryRecord(
        provider=_required_str(raw, "provider"),
        provider_id=_required_str(raw, "provider_id"),
        title=_required_str(raw, "title"),
        year=_optional_int(raw, "year", None),
        doi=_optional_str(raw, "doi"),
        abstract=_optional_str(raw, "abstract"),
        landing_page_url=_optional_str(raw, "landing_page_url"),
        open_access_url=_optional_str(raw, "open_access_url"),
        cited_by_count=_optional_int(raw, "cited_by_count", None),
        external_ids=_string_mapping(raw.get("external_ids", {}), "record.external_ids"),
        metadata=dict(metadata),
    )


def _snapshot_from_dict(raw: dict[str, Any]) -> SearchSnapshot:
    query = raw.get("query")
    if not isinstance(query, dict):
        raise TypeError("snapshot.query must be an object")
    records = raw.get("records", [])
    if not isinstance(records, list) or any(not isinstance(value, dict) for value in records):
        raise TypeError("snapshot.records must be a list of objects")
    return SearchSnapshot(
        snapshot_id=UUID(_required_str(raw, "snapshot_id")),
        created_at=datetime.fromisoformat(_required_str(raw, "created_at")),
        query=_query_from_dict(query),
        providers_used=_string_tuple(raw.get("providers_used", []), "snapshot.providers_used"),
        next_cursors=_string_mapping(raw.get("next_cursors", {}), "snapshot.next_cursors"),
        records=tuple(_record_from_dict(value) for value in records),
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} must be a non-empty string")
    return value


def _optional_str(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string or null")
    return value


def _optional_int(raw: dict[str, Any], key: str, default: int | None) -> int | None:
    value = raw.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer or null")
    return value


def _int_with_default(raw: dict[str, Any], key: str, default: int) -> int:
    value = _optional_int(raw, key, default)
    if value is None:
        raise TypeError(f"{key} must be an integer")
    return value


def _optional_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _string_mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object")
    invalid = any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    )
    if invalid:
        raise TypeError(f"{field} keys and values must be strings")
    return dict(value)


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{field} must be a list of strings")
    return tuple(value)
