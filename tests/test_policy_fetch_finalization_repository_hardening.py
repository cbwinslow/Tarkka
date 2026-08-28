from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tarkka.infrastructure.storage import json_policy_fetch_finalization_repository as module
from tarkka.infrastructure.storage.json_policy_fetch_finalization_repository import (
    JsonPolicyFetchFinalizationRepository,
)


def test_repository_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "journal"
    path.mkdir()

    with pytest.raises(ValueError, match="path is a directory"):
        JsonPolicyFetchFinalizationRepository(path)


def test_save_rejects_wrong_runtime_type(tmp_path: Path) -> None:
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")

    with pytest.raises(ValueError, match="finalization must be a PolicyFetchFinalization"):
        repository.save(object())  # type: ignore[arg-type]


def test_delete_rejects_wrong_runtime_type(tmp_path: Path) -> None:
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")

    with pytest.raises(ValueError, match="finalization must be a PolicyFetchFinalization"):
        repository.delete(object())  # type: ignore[arg-type]


def test_read_wraps_oserror_with_journal_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")

    def fail_read(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(OSError, match="unable to read policy finalization journal") as raised:
        repository._read()

    assert isinstance(raised.value.__cause__, OSError)


def test_read_rejects_invalid_json(tmp_path: Path) -> None:
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")
    repository.path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid policy finalization journal JSON"):
        repository._read()


def test_read_rejects_non_object_root(tmp_path: Path) -> None:
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")
    repository.path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="root must be an object"):
        repository._read()


def test_read_rejects_non_object_finalizations_bucket(tmp_path: Path) -> None:
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")
    repository.path.write_text(
        '{"schema_version": 1, "finalizations": []}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid policy finalization journal bucket"):
        repository._read()


def test_finalization_from_dict_rejects_non_object_record() -> None:
    with pytest.raises(RuntimeError, match="invalid policy finalization record"):
        module._finalization_from_dict([])  # type: ignore[arg-type]


def test_finalization_from_dict_rejects_non_object_response() -> None:
    with pytest.raises(RuntimeError, match="response must be an object") as raised:
        module._finalization_from_dict({"response": []})

    assert isinstance(raised.value.__cause__, ValueError)


def test_finalization_from_dict_rejects_non_object_headers() -> None:
    with pytest.raises(RuntimeError, match="response headers must be an object") as raised:
        module._finalization_from_dict({"response": {"headers": []}})

    assert isinstance(raised.value.__cause__, ValueError)


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))

    module._fsync_directory(tmp_path)
