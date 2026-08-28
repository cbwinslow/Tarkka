from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tarkka.infrastructure.storage import json_traversal_checkpoint_repository as module
from tarkka.infrastructure.storage.json_traversal_checkpoint_repository import (
    JsonTraversalCheckpointRepository,
)


def test_repository_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints"
    path.mkdir()

    with pytest.raises(ValueError, match="checkpoint path is a directory"):
        JsonTraversalCheckpointRepository(path)


def test_save_rejects_wrong_runtime_type(tmp_path: Path) -> None:
    repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")

    with pytest.raises(ValueError, match="checkpoint must be a TraversalCheckpoint"):
        repository.save(object())  # type: ignore[arg-type]


def test_get_rejects_non_uuid_checkpoint_id(tmp_path: Path) -> None:
    repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")

    with pytest.raises(ValueError, match="checkpoint ID must be a UUID"):
        repository.get("not-a-uuid")  # type: ignore[arg-type]


def test_read_wraps_oserror_with_catalog_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonTraversalCheckpointRepository(tmp_path / "checkpoints.json")

    def fail_read(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(OSError, match="unable to read traversal checkpoint catalog") as raised:
        repository._read()

    assert isinstance(raised.value.__cause__, OSError)


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))

    module._fsync_directory(tmp_path)
