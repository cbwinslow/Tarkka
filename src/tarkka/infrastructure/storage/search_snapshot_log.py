from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tarkka.domain.discovery import DiscoveryRecord, ResearchQuery, SearchSnapshot
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
        with exclusive_lock(self.path):
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())


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
