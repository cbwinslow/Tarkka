from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_OBSERVATION_ID = UUID("00000000-0000-0000-0000-000000000599")


def _repository(tmp_path: Path) -> tuple[JsonSourceObservationRepository, Path]:
    path = tmp_path / "source-observations.json"
    return JsonSourceObservationRepository(path), path


def test_source_observation_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid source observation catalog JSON"):
        repository.get_observation(_OBSERVATION_ID)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be an object"),
        (
            {"schema_version": 2, "observations": {}, "resource_links": {}},
            "invalid or unsupported source observation catalog",
        ),
        (
            {"schema_version": 1, "resource_links": {}},
            "invalid source observation catalog bucket: observations",
        ),
        (
            {"schema_version": 1, "observations": [], "resource_links": {}},
            "invalid source observation catalog bucket: observations",
        ),
        (
            {"schema_version": 1, "observations": {}, "resource_links": []},
            "invalid source observation catalog bucket: resource_links",
        ),
    ],
)
def test_source_observation_catalog_rejects_invalid_schema_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    repository, path = _repository(tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.get_observation(_OBSERVATION_ID)


def test_source_observation_catalog_does_not_repair_future_schema_on_write(
    tmp_path: Path,
) -> None:
    repository, path = _repository(tmp_path)
    future_catalog = {"schema_version": 99, "observations": {}, "resource_links": {}}
    path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid or unsupported source observation catalog"):
        repository.list_resource_links(_OBSERVATION_ID)

    assert json.loads(path.read_text(encoding="utf-8")) == future_catalog
