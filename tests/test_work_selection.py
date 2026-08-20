from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.work_selection import (
    SnapshotNotFoundError,
    SnapshotRecordConflictError,
    SnapshotRecordNotFoundError,
    WorkSelectionService,
)
from tarkka.application.works import WorkCatalogService, WorkIdentityConflictError
from tarkka.domain.discovery import DiscoveryRecord, ResearchQuery, SearchSnapshot
from tarkka.domain.work_identity import WorkIdentifier
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.search_snapshot_log import (
    JsonlSearchSnapshotLog,
    SnapshotDataError,
)
from tarkka.interfaces.cli import _work_payload, build_parser


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


def test_snapshot_log_rejects_corrupt_typed_fields(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.jsonl"
    snapshot = _snapshot()
    payload = {
        "snapshot_id": str(snapshot.snapshot_id),
        "created_at": snapshot.created_at.isoformat(),
        "query": {
            "text": "baseball prediction",
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
        "next_cursors": {"openalex": None},
        "records": [],
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SnapshotDataError, match="keys and values must be strings"):
        JsonlSearchSnapshotLog(path).get(snapshot.snapshot_id)


def test_snapshot_log_reports_invalid_provider_mode_as_corrupt_data(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.jsonl"
    snapshot = _snapshot()
    payload = {
        "snapshot_id": str(snapshot.snapshot_id),
        "created_at": snapshot.created_at.isoformat(),
        "query": {
            "text": "baseball prediction",
            "limit": 25,
            "cursor": None,
            "cursors": {},
            "mode": "not-a-mode",
            "providers": [],
            "require_open_access": False,
            "year_from": None,
            "year_to": None,
        },
        "providers_used": ["openalex"],
        "next_cursors": {},
        "records": [],
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SnapshotDataError, match="invalid snapshot"):
        JsonlSearchSnapshotLog(path).get(snapshot.snapshot_id)


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


def test_work_payload_preserves_multiple_values_for_one_identifier_scheme(tmp_path: Path) -> None:
    snapshots = JsonlSearchSnapshotLog(tmp_path / "snapshots.jsonl")
    snapshot = _snapshot()
    snapshots.record(snapshot)
    repository = JsonWorkRepository(tmp_path / "works.json")
    saved = WorkSelectionService(
        snapshots,
        WorkCatalogService(repository),
    ).save_snapshot_result(snapshot.snapshot_id, 0)

    with repository.transaction():
        repository.save_identifier(
            WorkIdentifier(
                identifier_id=uuid4(),
                work_id=saved.work.work_id,
                scheme="issn",
                value="1111-2222",
            )
        )
        repository.save_identifier(
            WorkIdentifier(
                identifier_id=uuid4(),
                work_id=saved.work.work_id,
                scheme="issn",
                value="3333-4444",
            )
        )

    payload = _work_payload(saved.work, repository)
    assert payload["identifiers"]["issn"] == ["1111-2222", "3333-4444"]  # type: ignore[index]


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


def test_work_selection_promotes_identity_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = JsonlSearchSnapshotLog(tmp_path / "snapshots.jsonl")
    snapshot = _snapshot()
    snapshots.record(snapshot)
    repository = JsonWorkRepository(tmp_path / "works.json")
    catalog = WorkCatalogService(repository)

    def _raise_conflict(*args: object, **kwargs: object) -> object:
        raise WorkIdentityConflictError("doi belongs to another work")

    monkeypatch.setattr(catalog, "persist_candidate", _raise_conflict)
    service = WorkSelectionService(snapshots, catalog)

    with pytest.raises(SnapshotRecordConflictError, match="existing canonical Work identity"):
        service.save_snapshot_result(snapshot.snapshot_id, 0)


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
