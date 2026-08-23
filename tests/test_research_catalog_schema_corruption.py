from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.infrastructure.storage.json_repository import JsonResearchRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000900")


def _repository(tmp_path: Path) -> tuple[JsonResearchRepository, Path]:
    path = tmp_path / "catalog.json"
    return JsonResearchRepository(path), path


def test_research_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to read Tarkka catalog"):
        repository.get_artifact(_ARTIFACT_ID)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be a JSON object"),
        (
            {"schema_version": 2, "artifacts": {}, "documents": {}},
            "unsupported Tarkka catalog schema version",
        ),
        (
            {"schema_version": 1, "artifacts": [], "documents": {}},
            "artifacts/documents must be JSON objects",
        ),
        (
            {"schema_version": 1, "artifacts": {}, "documents": []},
            "artifacts/documents must be JSON objects",
        ),
        (
            {"schema_version": 1, "documents": {}},
            "artifacts/documents must be JSON objects",
        ),
        (
            {"schema_version": 1, "artifacts": {}},
            "artifacts/documents must be JSON objects",
        ),
    ],
)
def test_research_catalog_rejects_invalid_schema_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    repository, path = _repository(tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.get_artifact(_ARTIFACT_ID)


def test_research_catalog_rejects_future_schema_without_rewriting_it(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    future_catalog = {
        "schema_version": 99,
        "artifacts": {},
        "documents": {},
    }
    path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported Tarkka catalog schema version"):
        repository.get_artifact(_ARTIFACT_ID)

    assert json.loads(path.read_text(encoding="utf-8")) == future_catalog
