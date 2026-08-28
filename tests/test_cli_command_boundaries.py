from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tarkka.application.work_selection import (
    SavedWorkSelection,
    SnapshotNotFoundError,
    SnapshotRecordConflictError,
)
from tarkka.domain.discovery import ResearchIntent, ResearchQuery
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Work
from tarkka.infrastructure.storage.search_snapshot_log import SnapshotDataError
from tarkka.interfaces import cli


def _args(**values: object) -> argparse.Namespace:
    return argparse.Namespace(**values)


def _manifest() -> ResourceManifest:
    return ResourceManifest(
        resource_id="doc:fixture",
        kind="document",
        title="Fixture",
        metadata={},
        available={"full_text": True},
        structure={"sections": 1},
        estimated_tokens={"manifest": 1},
    )


def test_cmd_ingest_translates_ingest_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Service:
        def ingest(self, path: object) -> object:
            raise FileNotFoundError(f"missing: {path}")

    monkeypatch.setattr(cli, "_runtime", lambda: (object(), object(), object()))
    monkeypatch.setattr(cli, "_ingest_service", lambda *args: _Service())

    assert cli._cmd_ingest(_args(path="missing.md")) == 2
    assert "error: missing: missing.md" in capsys.readouterr().err


def test_cmd_discover_serializes_successful_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_id = uuid4()

    class _Service:
        def __init__(self, providers: object, *, snapshot_recorder: object) -> None:
            assert providers
            assert snapshot_recorder is not None

        def discover(self, query: ResearchQuery) -> SimpleNamespace:
            record = SimpleNamespace(
                provider="crossref",
                provider_id="work-1",
                title="Result",
                year=2026,
                doi="10.1/result",
                cited_by_count=12,
                open_access_url="https://example.test/result",
            )
            return SimpleNamespace(
                snapshot_id=snapshot_id,
                query=query,
                providers_used=("crossref",),
                records=(record,),
                next_cursors={"crossref": "next"},
            )

    monkeypatch.setattr(cli, "DiscoveryService", _Service)
    monkeypatch.setattr(cli, "_discovery_providers", lambda: (object(),))
    monkeypatch.setattr(cli, "_snapshot_log", lambda: object())

    result = cli._cmd_discover(
        _args(
            provider=["crossref"],
            query="coverage",
            limit=5,
            cursor=["crossref=cursor"],
            intent=ResearchIntent.BROAD.value,
            open_access=True,
            year_from=2020,
            year_to=2026,
        )
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["snapshot_id"] == str(snapshot_id)
    assert payload["providers"] == ["crossref"]
    assert payload["next_cursors"] == {"crossref": "next"}
    assert payload["results"] == [
        {
            "cited_by_count": 12,
            "doi": "10.1/result",
            "index": 0,
            "open_access_url": "https://example.test/result",
            "provider": "crossref",
            "provider_id": "work-1",
            "title": "Result",
            "year": 2026,
        }
    ]


def test_cmd_discover_translates_invalid_provider_policy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli._cmd_discover(
        _args(
            provider=["auto", "crossref"],
            query="coverage",
            limit=5,
            cursor=None,
            intent=ResearchIntent.BROAD.value,
            open_access=False,
            year_from=None,
            year_to=None,
        )
    )

    assert result == 2
    assert "provider 'auto' cannot be combined" in capsys.readouterr().err


def _patch_work_save_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    outcome: SavedWorkSelection | Exception,
) -> None:
    class _Service:
        def __init__(self, *, snapshots: object, catalog: object) -> None:
            assert snapshots is not None
            assert catalog is not None

        def save_snapshot_result(self, snapshot_id: UUID, index: int) -> SavedWorkSelection:
            if isinstance(outcome, Exception):
                raise outcome
            assert snapshot_id == outcome.snapshot_id
            assert index == outcome.result_index
            return outcome

    monkeypatch.setattr(cli, "_work_repository", lambda: object())
    monkeypatch.setattr(cli, "_snapshot_log", lambda: object())
    monkeypatch.setattr(cli, "WorkCatalogService", lambda repository: object())
    monkeypatch.setattr(cli, "WorkSelectionService", _Service)


def test_cmd_work_save_serializes_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_id = uuid4()
    work = Work(work_id=uuid4(), title="Selected")
    selection = SavedWorkSelection(snapshot_id=snapshot_id, result_index=2, work=work)
    _patch_work_save_dependencies(monkeypatch, selection)
    monkeypatch.setattr(cli, "_work_payload", lambda selected, repository: {"title": selected.title})

    assert cli._cmd_work_save(_args(snapshot_id=snapshot_id, index=2)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"result_index": 2, "snapshot_id": str(snapshot_id), "title": "Selected"}


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (SnapshotRecordConflictError("collision"), 3, "identity conflict: collision"),
        (SnapshotDataError("broken"), 2, "corrupted snapshot data: broken"),
        (SnapshotNotFoundError("missing"), 2, "error: missing"),
    ],
)
def test_cmd_work_save_translates_selection_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    status: int,
    message: str,
) -> None:
    _patch_work_save_dependencies(monkeypatch, error)

    assert cli._cmd_work_save(_args(snapshot_id=uuid4(), index=0)) == status
    assert message in capsys.readouterr().err


def test_cmd_work_show_handles_missing_success_and_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work_id = uuid4()

    class _Repository:
        value: Work | None = None
        failure: Exception | None = None

        def get_work(self, requested: UUID) -> Work | None:
            assert requested == work_id
            if self.failure is not None:
                raise self.failure
            return self.value

    repository = _Repository()
    monkeypatch.setattr(cli, "_work_repository", lambda: repository)
    monkeypatch.setattr(cli, "_work_payload", lambda work, repo: {"title": work.title})

    assert cli._cmd_work_show(_args(work_id=work_id)) == 2
    assert "work not found" in capsys.readouterr().err

    repository.value = Work(work_id=work_id, title="Present")
    assert cli._cmd_work_show(_args(work_id=work_id)) == 0
    assert json.loads(capsys.readouterr().out) == {"title": "Present"}

    repository.failure = RuntimeError("catalog offline")
    assert cli._cmd_work_show(_args(work_id=work_id)) == 2
    assert "catalog offline" in capsys.readouterr().err


def test_cmd_work_enrich_handles_success_and_service_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work_id = uuid4()
    work = Work(work_id=work_id, title="Enriched")

    class _Service:
        failure = False

        def __init__(self, repository: object) -> None:
            assert repository is not None

        def enrich_by_doi(self, requested: UUID, provider: object) -> Work:
            assert requested == work_id
            assert provider is not None
            if self.failure:
                raise RuntimeError("enrichment unavailable")
            return work

    service = _Service(object())
    monkeypatch.setattr(cli, "_work_repository", lambda: object())
    monkeypatch.setattr(cli, "WorkCatalogService", lambda repository: service)
    monkeypatch.setattr(cli, "_crossref", lambda: object())
    monkeypatch.setattr(cli, "_work_payload", lambda selected, repository: {"title": selected.title})

    assert cli._cmd_work_enrich(_args(work_id=work_id)) == 0
    assert json.loads(capsys.readouterr().out) == {"title": "Enriched"}

    service.failure = True
    assert cli._cmd_work_enrich(_args(work_id=work_id)) == 2
    assert "enrichment unavailable" in capsys.readouterr().err


def test_cmd_work_acquire_serializes_result_and_translates_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work_id = uuid4()
    artifact_id = uuid4()
    document_id = uuid4()
    link_id = uuid4()

    class _Service:
        failure = False

        def acquire(self, requested: UUID) -> SimpleNamespace:
            assert requested == work_id
            if self.failure:
                raise RuntimeError("acquisition unavailable")
            return SimpleNamespace(
                resource=SimpleNamespace(provider="arxiv", source_uri="https://example.test/file"),
                ingest=SimpleNamespace(
                    artifact=SimpleNamespace(artifact_id=artifact_id),
                    document=SimpleNamespace(document_id=document_id),
                    manifest=_manifest(),
                ),
                work_document_link=SimpleNamespace(link_id=link_id),
            )

    service = _Service()
    monkeypatch.setattr(cli, "_runtime", lambda: (object(), object(), object()))
    monkeypatch.setattr(cli, "_work_repository", lambda: object())
    monkeypatch.setattr(cli, "_ingest_service", lambda *args: object())
    monkeypatch.setattr(cli, "FullTextAcquisitionService", lambda **kwargs: service)

    assert cli._cmd_work_acquire(_args(work_id=work_id)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["work_id"] == str(work_id)
    assert payload["provider"] == "arxiv"
    assert payload["artifact_id"] == str(artifact_id)
    assert payload["document_id"] == str(document_id)
    assert payload["work_document_link_id"] == str(link_id)

    service.failure = True
    assert cli._cmd_work_acquire(_args(work_id=work_id)) == 2
    assert "acquisition unavailable" in capsys.readouterr().err


def test_cmd_inspect_serializes_existing_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = uuid4()

    class _Repository:
        def get_manifest(self, requested: UUID) -> ResourceManifest:
            assert requested == document_id
            return _manifest()

    monkeypatch.setattr(cli, "_runtime", lambda: (object(), _Repository(), object()))

    assert cli._cmd_inspect(_args(document_id=document_id)) == 0
    assert "id: doc:fixture" in capsys.readouterr().out


def test_cmd_read_handles_full_selected_and_invalid_sections(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = uuid4()
    document = SimpleNamespace(
        sections=(
            SimpleNamespace(passages=(SimpleNamespace(text="first"),)),
            SimpleNamespace(passages=(SimpleNamespace(text="second"),)),
        )
    )

    class _Repository:
        value: object | None = document

        def get_document(self, requested: UUID) -> object | None:
            assert requested == document_id
            return self.value

    repository = _Repository()
    monkeypatch.setattr(cli, "_runtime", lambda: (object(), repository, object()))

    assert cli._cmd_read(_args(document_id=document_id, section=None)) == 0
    assert capsys.readouterr().out == "firstsecond"

    assert cli._cmd_read(_args(document_id=document_id, section=1)) == 0
    assert capsys.readouterr().out == "second"

    for section in (-1, 2):
        assert cli._cmd_read(_args(document_id=document_id, section=section)) == 2
        assert "section index out of range" in capsys.readouterr().err

    repository.value = None
    assert cli._cmd_read(_args(document_id=document_id, section=None)) == 2
    assert "document not found" in capsys.readouterr().err
