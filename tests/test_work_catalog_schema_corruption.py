from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_WORK_ID = UUID("00000000-0000-0000-0000-000000000600")


def _repository(tmp_path: Path) -> tuple[JsonWorkRepository, Path]:
    path = tmp_path / "works.json"
    return JsonWorkRepository(path), path


def test_work_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to read Tarkka Work catalog"):
        repository.get_work(_WORK_ID)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be an object"),
        (
            {"schema_version": 2, "works": {}, "identifiers": {}, "source_records": {}},
            "unsupported Tarkka Work catalog schema version",
        ),
        (
            {"schema_version": 1, "identifiers": {}, "source_records": {}},
            "works must be an object",
        ),
        (
            {"schema_version": 1, "works": [], "identifiers": {}, "source_records": {}},
            "works must be an object",
        ),
        (
            {"schema_version": 1, "works": {}, "identifiers": [], "source_records": {}},
            "identifiers must be an object",
        ),
        (
            {"schema_version": 1, "works": {}, "identifiers": {}, "source_records": []},
            "source_records must be an object",
        ),
    ],
)
def test_work_catalog_rejects_invalid_schema_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    repository, path = _repository(tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.get_work(_WORK_ID)


def test_work_catalog_does_not_repair_future_schema_in_transaction(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    future_catalog = {
        "schema_version": 99,
        "works": {},
        "identifiers": {},
        "source_records": {},
    }
    path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported Tarkka Work catalog schema version"):
        with repository.transaction():
            pytest.fail("transaction body must not run for an unsupported catalog")

    assert json.loads(path.read_text(encoding="utf-8")) == future_catalog
