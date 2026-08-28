from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tarkka.infrastructure.storage import json_verification_repository
from tarkka.infrastructure.storage.json_verification_repository import (
    JsonVerificationRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_repository_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "verifications"
    path.mkdir()

    with pytest.raises(ValueError, match="catalog path is a directory"):
        JsonVerificationRepository(path)


def test_open_existing_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "verifications"
    path.mkdir()

    with pytest.raises(ValueError, match="catalog path is a directory"):
        JsonVerificationRepository.open_existing(path)


def test_list_relations_rejects_negative_pagination(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")

    with pytest.raises(ValueError, match="offset and limit must be non-negative"):
        repository.list_relations(uuid4(), offset=-1)


def test_read_rejects_invalid_json_with_catalog_context(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    repository.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to read verification catalog") as raised:
        repository._read()

    assert isinstance(raised.value.__cause__, json.JSONDecodeError)


def test_read_rejects_non_object_root(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    repository.path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="root must be an object"):
        repository._read()


def test_read_rejects_invalid_relations_bucket(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    repository.path.write_text(
        json.dumps({"schema_version": 1, "relations": []}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="catalog bucket: relations"):
        repository._read()


def test_read_rejects_non_object_relation_entry(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    repository.path.write_text(
        json.dumps({"schema_version": 1, "relations": {"bad": []}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid verification catalog relation entry"):
        repository._read()


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        json_verification_repository,
        "os",
        SimpleNamespace(name="nt"),
    )

    json_verification_repository._fsync_directory(tmp_path)
