from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tarkka.application.document_context_packages import (
    MAX_CONTEXT_PACKAGE_SECTIONS,
    DocumentContextPackageService,
)
from tarkka.domain.context_packages import SavedDocumentContextPackage
from tarkka.infrastructure.storage import json_context_package_repository as context_repository
from tarkka.infrastructure.storage.json_context_package_repository import (
    ContextPackageConflictError,
    JsonDocumentContextPackageRepository,
)


def _saved_package() -> SavedDocumentContextPackage:
    return SavedDocumentContextPackage(
        context_package_id=UUID("00000000-0000-0000-0000-000000000201"),
        document_id=UUID("00000000-0000-0000-0000-000000000202"),
        section_ids=(
            UUID("00000000-0000-0000-0000-000000000203"),
            UUID("00000000-0000-0000-0000-000000000204"),
        ),
        estimated_tokens=42,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


def _catalog_payload(package: SavedDocumentContextPackage) -> dict[str, object]:
    return {
        "schema_version": 1,
        "packages": {
            str(package.context_package_id): {
                "context_package_id": str(package.context_package_id),
                "document_id": str(package.document_id),
                "section_ids": [str(section_id) for section_id in package.section_ids],
                "estimated_tokens": package.estimated_tokens,
                "created_at": package.created_at.isoformat(),
            }
        },
    }


def test_document_context_package_rejects_more_than_the_configured_section_limit() -> None:
    service = DocumentContextPackageService(documents=object())  # type: ignore[arg-type]
    section_ids = tuple(uuid4() for _ in range(MAX_CONTEXT_PACKAGE_SECTIONS + 1))

    with pytest.raises(ValueError, match="section maximum"):
        service.build(uuid4(), section_ids)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"section_ids": ()}, "at least one section"),
        ({"section_ids": (UUID(int=1), UUID(int=1))}, "must be unique"),
        ({"estimated_tokens": -1}, "non-negative"),
    ],
)
def test_saved_context_package_rejects_invalid_durable_selections(
    kwargs: dict[str, object],
    message: str,
) -> None:
    base = _saved_package()

    with pytest.raises(ValueError, match=message):
        replace(base, **kwargs)  # type: ignore[arg-type]


def test_json_context_package_repository_rejects_a_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "catalog"
    path.mkdir()

    with pytest.raises(ValueError, match="path is a directory"):
        JsonDocumentContextPackageRepository(path)


def test_json_context_package_repository_is_idempotent_but_rejects_conflicts(
    tmp_path: Path,
) -> None:
    package = _saved_package()
    repository = JsonDocumentContextPackageRepository(tmp_path / "context-packages.json")

    repository.save(package)
    repository.save(replace(package, created_at=datetime(2027, 1, 1, tzinfo=UTC)))
    assert repository.get(package.context_package_id) == package

    with pytest.raises(ContextPackageConflictError, match="conflicting context package"):
        repository.save(replace(package, estimated_tokens=package.estimated_tokens + 1))


def test_json_context_package_repository_wraps_unreadable_or_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "context-packages.json"
    repository = JsonDocumentContextPackageRepository(path)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to read context-package catalog"):
        repository.get(uuid4())

    path.unlink()
    with pytest.raises(RuntimeError, match="unable to read context-package catalog"):
        repository.get(uuid4())


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        ({"schema_version": 2, "packages": {}}, "invalid or unsupported"),
        ({"schema_version": 1, "packages": []}, "bucket: packages"),
        ({"schema_version": 1, "packages": {"entry": []}}, "catalog entry"),
    ],
)
def test_json_context_package_repository_rejects_invalid_catalog_structure(
    tmp_path: Path,
    catalog: dict[str, object],
    message: str,
) -> None:
    path = tmp_path / "context-packages.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    repository = JsonDocumentContextPackageRepository(path)

    with pytest.raises(RuntimeError, match=message):
        repository.get(uuid4())


def test_json_context_package_repository_rejects_non_string_catalog_keys_from_decoder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "context-packages.json"
    path.write_text("{}", encoding="utf-8")
    repository = JsonDocumentContextPackageRepository(path)
    monkeypatch.setattr(
        context_repository.json,
        "loads",
        lambda _: {"schema_version": 1, "packages": {7: {}}},
    )

    with pytest.raises(RuntimeError, match="catalog entry 7"):
        repository.get(uuid4())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(context_package_id=str(uuid4())), "does not match"),
        (lambda payload: payload.pop("document_id"), "document_id"),
        (lambda payload: payload.update(section_ids="bad"), "section_ids"),
        (lambda payload: payload.update(section_ids=[7]), "section_ids"),
        (lambda payload: payload.update(section_ids=["not-a-uuid"]), "badly formed"),
        (lambda payload: payload.update(estimated_tokens=True), "estimated_tokens"),
        (lambda payload: payload.update(estimated_tokens="42"), "estimated_tokens"),
        (lambda payload: payload.update(created_at="not-a-date"), "Invalid isoformat"),
    ],
)
def test_json_context_package_repository_rejects_corrupt_package_entries(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    package = _saved_package()
    catalog = _catalog_payload(package)
    packages = catalog["packages"]
    assert isinstance(packages, dict)
    payload = packages[str(package.context_package_id)]
    assert isinstance(payload, dict)
    mutate(payload)  # type: ignore[operator]
    path = tmp_path / "context-packages.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    repository = JsonDocumentContextPackageRepository(path)

    with pytest.raises(RuntimeError, match=message):
        repository.get(package.context_package_id)


def test_json_context_package_repository_keeps_original_catalog_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "context-packages.json"
    repository = JsonDocumentContextPackageRepository(path)
    original = path.read_text(encoding="utf-8")

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(context_repository.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        repository.save(_saved_package())

    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".tarkka-context-packages-*")) == []


def test_context_package_directory_fsync_is_a_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(context_repository.os, "name", "nt")

    context_repository._fsync_directory(tmp_path)
