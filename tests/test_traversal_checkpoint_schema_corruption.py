from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_CHECKPOINT_ID = UUID("00000000-0000-0000-0000-000000000604")


def _repository(tmp_path: Path) -> tuple[JsonTraversalCheckpointRepository, Path]:
    path = tmp_path / "checkpoints.json"
    return JsonTraversalCheckpointRepository(path), path


def test_traversal_checkpoint_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid traversal checkpoint JSON"):
        repository.get(_CHECKPOINT_ID)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be an object"),
        (
            {"schema_version": 2, "checkpoints": {}},
            "invalid or unsupported traversal checkpoint catalog",
        ),
        (
            {"schema_version": 1},
            "invalid traversal checkpoint catalog bucket: checkpoints",
        ),
        (
            {"schema_version": 1, "checkpoints": []},
            "invalid traversal checkpoint catalog bucket: checkpoints",
        ),
    ],
)
def test_traversal_checkpoint_catalog_rejects_invalid_schema_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    repository, path = _repository(tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.get(_CHECKPOINT_ID)


def test_traversal_checkpoint_catalog_does_not_repair_future_schema(
    tmp_path: Path,
) -> None:
    repository, path = _repository(tmp_path)
    future_catalog = {"schema_version": 99, "checkpoints": {}}
    path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="invalid or unsupported traversal checkpoint catalog",
    ):
        repository.get(_CHECKPOINT_ID)

    assert json.loads(path.read_text(encoding="utf-8")) == future_catalog
