from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from tarkka.domain.discovery import DiscoveryRecord, ResearchQuery, SearchSnapshot
from tarkka.domain.models import Work
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.work_repository import PostgresWorkRepository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.search_snapshot_log import JsonlSearchSnapshotLog
from tarkka.interfaces.cli import _work_repository, main


def test_work_repository_defaults_to_local_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    monkeypatch.delenv("TARKKA_WORK_BACKEND", raising=False)
    monkeypatch.setenv("TARKKA_DATABASE_URL", "postgresql://must-not-be-used")

    repository = _work_repository()

    assert isinstance(repository, JsonWorkRepository)
    assert repository.path == tmp_path / "works.json"


def test_work_repository_accepts_explicit_json_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    monkeypatch.setenv("TARKKA_WORK_BACKEND", " json ")

    assert isinstance(_work_repository(), JsonWorkRepository)


def test_work_repository_selects_postgres_only_when_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", "postgres")
    monkeypatch.setenv("TARKKA_DATABASE_URL", "postgresql://configured")

    repository = _work_repository()

    assert isinstance(repository, PostgresWorkRepository)


def test_work_repository_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", "sqlite")

    with pytest.raises(ValueError, match="unsupported TARKKA_WORK_BACKEND 'sqlite'"):
        _work_repository()


def test_work_repository_requires_database_url_for_explicit_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", "postgres")
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="TARKKA_DATABASE_URL is required"):
        _work_repository()


@pytest.mark.parametrize(
    ("backend", "expected"),
    [
        ("sqlite", "unsupported TARKKA_WORK_BACKEND 'sqlite'"),
        ("postgres", "TARKKA_DATABASE_URL is required"),
    ],
)
def test_work_cli_reports_backend_configuration_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    backend: str,
    expected: str,
) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", backend)
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)

    assert main(["work", "show", str(uuid4())]) == 2

    assert expected in capsys.readouterr().err


def test_local_work_cli_flow_uses_json_backend_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    monkeypatch.delenv("TARKKA_WORK_BACKEND", raising=False)
    snapshot = SearchSnapshot(
        snapshot_id=uuid4(),
        query=ResearchQuery("backend selection"),
        providers_used=("openalex",),
        records=(
            DiscoveryRecord(
                provider="openalex",
                provider_id="W-backend",
                title="Backend selection fixture",
            ),
        ),
    )
    JsonlSearchSnapshotLog(tmp_path / "search_snapshots.jsonl").record(snapshot)

    assert main(["work", "save", "--snapshot", str(snapshot.snapshot_id), "--index", "0"]) == 0
    work_id = json.loads(capsys.readouterr().out)["work_id"]

    assert main(["work", "show", work_id]) == 0
    assert json.loads(capsys.readouterr().out)["work_id"] == work_id

    assert main(["work", "acquire", work_id]) == 2
    assert "no full-text representation found" in capsys.readouterr().err


def test_work_show_reports_payload_repository_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingPayloadRepository:
        def get_work(self, work_id: object) -> Work:
            del work_id
            return Work(work_id=uuid4(), title="Payload failure fixture")

        def list_identifiers(self, work_id: object) -> tuple[object, ...]:
            del work_id
            raise RuntimeError("database connection lost")

        def list_source_records(self, work_id: object) -> tuple[object, ...]:
            del work_id
            return ()

    monkeypatch.setattr("tarkka.interfaces.cli._work_repository", FailingPayloadRepository)

    assert main(["work", "show", str(uuid4())]) == 2
    assert "error: database connection lost" in capsys.readouterr().err


def test_work_cli_reports_postgres_driver_failures_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class OperationalError(Exception):
        pass

    driver = ModuleType("psycopg")
    driver.Error = OperationalError  # type: ignore[attr-defined]
    driver.OperationalError = OperationalError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", driver)

    def _raise_operational_error(_: PostgresSettings) -> object:
        raise OperationalError("connection refused")

    repository = PostgresWorkRepository(
        PostgresSettings("postgresql://configured"),
        connection_factory=_raise_operational_error,
    )
    monkeypatch.setattr("tarkka.interfaces.cli._work_repository", lambda: repository)

    assert main(["work", "show", str(uuid4())]) == 2

    stderr = capsys.readouterr().err
    assert "error: PostgreSQL operation failed" in stderr
    assert "Traceback" not in stderr
