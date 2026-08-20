from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from tarkka.domain.discovery import ResearchIntent, ResearchQuery, SearchSnapshot
from tarkka.infrastructure.storage.search_snapshot_log import JsonlSearchSnapshotLog


def test_snapshot_round_trips_research_intent(tmp_path: Path) -> None:
    log = JsonlSearchSnapshotLog(tmp_path / "snapshots.jsonl")
    snapshot = SearchSnapshot(
        snapshot_id=uuid4(),
        query=ResearchQuery("query", intent=ResearchIntent.CITATIONS),
        providers_used=("semantic-scholar",),
        records=(),
    )

    log.record(snapshot)
    loaded = log.get(snapshot.snapshot_id)

    assert loaded is not None
    assert loaded.query.intent is ResearchIntent.CITATIONS


def test_old_snapshot_without_intent_defaults_to_broad(tmp_path: Path) -> None:
    snapshot_id = uuid4()
    path = tmp_path / "snapshots.jsonl"
    path.write_text(
        json.dumps(
            {
                "snapshot_id": str(snapshot_id),
                "created_at": "2026-08-20T00:00:00+00:00",
                "query": {
                    "text": "legacy query",
                    "limit": 25,
                    "cursor": None,
                    "cursors": {},
                    "mode": "auto",
                    "providers": [],
                    "require_open_access": False,
                    "year_from": None,
                    "year_to": None,
                },
                "providers_used": ["openalex"],
                "next_cursors": {},
                "records": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = JsonlSearchSnapshotLog(path).get(snapshot_id)

    assert loaded is not None
    assert loaded.query.intent is ResearchIntent.BROAD
