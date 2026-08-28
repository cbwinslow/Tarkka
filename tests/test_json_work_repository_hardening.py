from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.storage import json_work_repository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository

_OBSERVED_AT = datetime(2026, 8, 28, tzinfo=UTC)


def test_nested_transaction_is_rejected_and_outer_state_is_cleared(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")

    with (
        repository.transaction(),
        pytest.raises(RuntimeError, match="nested Work repository transactions"),
        repository.transaction(),
    ):
        pytest.fail("nested transaction body must not run")

    assert repository._transaction_data is None


def test_save_identifier_outside_transaction_persists_directly(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    work_id = uuid4()
    identifier = WorkIdentifier(
        identifier_id=uuid4(),
        work_id=work_id,
        scheme="doi",
        value="10.1000/direct",
        created_at=_OBSERVED_AT,
    )

    repository.save_identifier(identifier)

    assert repository.list_identifiers(work_id) == (identifier,)


def test_save_source_record_outside_transaction_persists_directly(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    work_id = uuid4()
    source_record = WorkSourceRecord(
        source_record_id=uuid4(),
        work_id=work_id,
        observed_at=_OBSERVED_AT,
        record=DiscoveryRecord(
            provider="openalex",
            provider_id="W-direct",
            title="Direct persistence",
        ),
    )

    repository.save_source_record(source_record)

    assert repository.list_source_records(work_id) == (source_record,)


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json_work_repository, "os", SimpleNamespace(name="nt"))

    json_work_repository._fsync_directory(tmp_path)
