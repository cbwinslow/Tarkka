from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.work_selection import (
    SnapshotNotFoundError,
    SnapshotRecordNotFoundError,
    WorkSelectionService,
)
from tarkka.application.works import WorkCatalogService
from tarkka.domain.discovery import DiscoveryRecord, ResearchQuery, SearchSnapshot
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.search_snapshot_log import JsonlSearchSnapshotLog
from tarkka.interfaces.cli import build_parser


def _snapshot() -> SearchSnapshot:
    return SearchSnapshot(
        snapshot_id=uuid4(),
        query=ResearchQuery("baseball prediction"),
        providers_used=("openalex",),
        records=(
            DiscoveryRecord(
                provider="openalex",
                provider_id="W123",
                title="Baseball prediction model",
                year=2024,
                doi="10.1234/example",
                external_ids={"openalex": "W123", "doi": "10.1234/example"},
            ),
        ),
    )


def test_snapshot_log_round_trips_snapshot(tmp_path: Path) -> None:
    log = JsonlSearchSnapshotLog(tmp_path / "snapshots.jsonl")
    snapshot = _snapshot()

    log.record(snapshot)
    restored = log.get(snapshot.snapshot_id)

    assert restored is not None
    assert restored.snapshot_id == snapshot.snapshot_id
    assert restored.query.text == "baseball prediction"
    assert restored.records[0].provider_id == "W123"
    assert restored.records[0].doi == "10.1234/example"


def test_work_selection_persists_explicit_snapshot_result(tmp_path: Path) -> None:
    snapshots = JsonlSearchSnapshotLog(tmp_path / "snapshots.jsonl")
    snapshot = _snapshot()
    snapshots.record(snapshot)
    repository = JsonWorkRepository(tmp_path / "works.json")
    service = WorkSelectionService(snapshots, WorkCatalogService(repository))

    saved = service.save_snapshot_result(snapshot.snapshot_id, 0)
    repeated = service.save_snapshot_result(snapshot.snapshot_id, 0)

    assert saved.work.work_id == repeated.work.work_id
    assert repository.find_work_by_identifier("doi", "10.1234/example") == saved.work
    assert len(repository.list_source_records(saved.work.work_id)) == 1


def test_work_selection_rejects_missing_snapshot_and_index(tmp_path: Path) -> None:
    snapshots = JsonlSearchSnapshotLog(tmp_path / "snapshots.jsonl")
    repository = JsonWorkRepository(tmp_path / "works.json")
    service = WorkSelectionService(snapshots, WorkCatalogService(repository))

    with pytest.raises(SnapshotNotFoundError):
        service.save_snapshot_result(uuid4(), 0)

    snapshot = _snapshot()
    snapshots.record(snapshot)
    with pytest.raises(SnapshotRecordNotFoundError):
        service.save_snapshot_result(snapshot.snapshot_id, 2)


def test_work_cli_exposes_selection_and_enrichment_commands() -> None:
    snapshot_id = uuid4()
    work_id = uuid4()

    save_args = build_parser().parse_args(
        ["work", "save", "--snapshot", str(snapshot_id), "--index", "0"]
    )
    show_args = build_parser().parse_args(["work", "show", str(work_id)])
    enrich_args = build_parser().parse_args(["work", "enrich", str(work_id)])

    assert save_args.snapshot_id == snapshot_id
    assert save_args.index == 0
    assert show_args.work_id == work_id
    assert enrich_args.work_id == work_id
