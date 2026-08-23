from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.infrastructure.storage.json_extraction_repository import (
    JsonExtractionRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_EXTRACTION_ID = UUID("00000000-0000-0000-0000-000000000603")


def _repository(tmp_path: Path) -> tuple[JsonExtractionRepository, Path]:
    path = tmp_path / "extractions.json"
    return JsonExtractionRepository(path), path


def test_extraction_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to read extraction catalog"):
        repository.get_extraction(_EXTRACTION_ID)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be an object"),
        (
            {"schema_version": 2, "batches": {}},
            "invalid or unsupported extraction catalog",
        ),
        (
            {"schema_version": 1},
            "invalid or unsupported extraction catalog",
        ),
        (
            {"schema_version": 1, "batches": []},
            "invalid or unsupported extraction catalog",
        ),
    ],
)
def test_extraction_catalog_rejects_invalid_schema_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    repository, path = _repository(tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.get_extraction(_EXTRACTION_ID)


def test_extraction_catalog_does_not_repair_future_schema(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    future_catalog = {"schema_version": 99, "batches": {}}
    path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid or unsupported extraction catalog"):
        repository.get_extraction(_EXTRACTION_ID)

    assert json.loads(path.read_text(encoding="utf-8")) == future_catalog
