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
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    if raw.get("snapshot_id") == str(snapshot_id):
                        return _snapshot_from_dict(raw)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
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
    return ResearchQuery(
        text=str(raw["text"]),
        limit=int(raw.get("limit", 25)),
        cursor=raw.get("cursor"),
        cursors={str(key): str(value) for key, value in dict(raw.get("cursors", {})).items()},
        mode=ProviderMode(str(raw.get("mode", ProviderMode.AUTO.value))),
        providers=tuple(str(value) for value in raw.get("providers", [])),
        require_open_access=bool(raw.get("require_open_access", False)),
        year_from=raw.get("year_from"),
        year_to=raw.get("year_to"),
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
    external_ids = {
        str(key): str(value)
        for key, value in dict(raw.get("external_ids", {})).items()
    }
    return DiscoveryRecord(
        provider=str(raw["provider"]),
        provider_id=str(raw["provider_id"]),
        title=str(raw["title"]),
        year=raw.get("year"),
        doi=raw.get("doi"),
        abstract=raw.get("abstract"),
        landing_page_url=raw.get("landing_page_url"),
        open_access_url=raw.get("open_access_url"),
        cited_by_count=raw.get("cited_by_count"),
        external_ids=external_ids,
        metadata=dict(raw.get("metadata", {})),
    )


def _snapshot_from_dict(raw: dict[str, Any]) -> SearchSnapshot:
    next_cursors = {
        str(key): str(value)
        for key, value in dict(raw.get("next_cursors", {})).items()
    }
    return SearchSnapshot(
        snapshot_id=UUID(str(raw["snapshot_id"])),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        query=_query_from_dict(dict(raw["query"])),
        providers_used=tuple(str(value) for value in raw.get("providers_used", [])),
        next_cursors=next_cursors,
        records=tuple(_record_from_dict(dict(value)) for value in raw.get("records", [])),
    )
