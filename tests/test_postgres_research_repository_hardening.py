from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.manifest import ResourceManifest, build_document_manifest
from tarkka.domain.models import Artifact, Document, Section
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings
from tarkka.infrastructure.postgres.research_repository import (
    PostgresResearchRepository,
    _manifest_from_json,
)

_SETTINGS = PostgresSettings("postgresql://unused")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000fa01")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fa02")
_ROOT_SECTION_ID = UUID("00000000-0000-0000-0000-00000000fa03")
_CHILD_SECTION_ID = UUID("00000000-0000-0000-0000-00000000fa04")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    rowcount: int = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)
    closed: bool = False
    commits: int = 0
    rollbacks: int = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: Any) -> None:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        raise self.error


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="a" * 64,
        size_bytes=12,
        media_type="text/plain",
        storage_key=PurePosixPath("artifacts/aa/file.txt"),
        original_name="file.txt",
        acquired_at=_CREATED_AT,
        source_uri="https://example.test/file.txt",
    )


def _artifact_row(artifact: Artifact) -> tuple[Any, ...]:
    return (
        artifact.artifact_id,
        artifact.sha256,
        artifact.size_bytes,
        artifact.media_type,
        artifact.storage_key.as_posix(),
        artifact.original_name,
        artifact.acquired_at,
        artifact.source_uri,
    )


def _document() -> Document:
    return Document(
        document_id=_DOCUMENT_ID,
        artifact_id=_ARTIFACT_ID,
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(),
        normalized_at=_CREATED_AT,
    )


def _document_row(document: Document) -> tuple[Any, ...]:
    return (
        document.document_id,
        document.artifact_id,
        document.title,
        document.parser_name,
        document.parser_version,
        document.normalized_at,
    )


def _repository(connection: _Connection) -> PostgresResearchRepository:
    return PostgresResearchRepository(_SETTINGS, connection_factory=lambda _: connection)


def _patch_document_reads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    artifact: Artifact,
    document: Document | None,
    manifest: ResourceManifest | None,
) -> None:
    monkeypatch.setattr(
        PostgresResearchRepository,
        "_get_artifact",
        staticmethod(lambda *_: artifact),
    )
    monkeypatch.setattr(
        PostgresResearchRepository,
        "_get_document",
        staticmethod(lambda *_: document),
    )
    monkeypatch.setattr(
        PostgresResearchRepository,
        "_get_manifest",
        staticmethod(lambda *_: manifest),
    )


def test_artifact_conflict_requires_existing_matching_content() -> None:
    artifact = _artifact()

    missing = _Connection([_Cursor(rowcount=0), _Cursor(row=None)])
    with pytest.raises(ValueError, match="conflicting artifact"):
        _repository(missing).save_artifact(artifact)

    different = replace(artifact, size_bytes=artifact.size_bytes + 1)
    mismatch = _Connection([_Cursor(rowcount=0), _Cursor(row=_artifact_row(different))])
    with pytest.raises(ValueError, match="conflicting artifact"):
        _repository(mismatch).save_artifact(artifact)


def test_artifact_getter_returns_found_and_missing_rows() -> None:
    artifact = _artifact()
    found = _Connection([_Cursor(row=_artifact_row(artifact))])
    missing = _Connection([_Cursor(row=None)])

    assert _repository(found).get_artifact(_ARTIFACT_ID) == artifact
    assert _repository(missing).get_artifact(_ARTIFACT_ID) is None
    assert found.closed and missing.closed


def test_document_write_rejects_missing_artifact_before_insert() -> None:
    artifact = _artifact()
    document = _document()
    connection = _Connection([_Cursor(row=None)])

    with pytest.raises(ValueError, match="artifact not found for document"):
        _repository(connection).save_document(document, build_document_manifest(document, artifact))

    assert len(connection.calls) == 1


def test_document_retry_rejects_missing_existing_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    document = _document()
    manifest = build_document_manifest(document, artifact)
    _patch_document_reads(monkeypatch, artifact=artifact, document=None, manifest=manifest)

    with pytest.raises(ValueError, match="conflicting document"):
        _repository(_Connection([_Cursor(rowcount=0)])).save_document(document, manifest)


def test_document_retry_rejects_changed_document_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    document = _document()
    manifest = build_document_manifest(document, artifact)
    _patch_document_reads(
        monkeypatch,
        artifact=artifact,
        document=replace(document, title="Changed"),
        manifest=manifest,
    )

    with pytest.raises(ValueError, match="conflicting document"):
        _repository(_Connection([_Cursor(rowcount=0)])).save_document(document, manifest)


def test_document_retry_rejects_changed_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _artifact()
    document = _document()
    manifest = build_document_manifest(document, artifact)
    _patch_document_reads(
        monkeypatch,
        artifact=artifact,
        document=document,
        manifest=replace(manifest, title="Changed manifest"),
    )

    with pytest.raises(ValueError, match="conflicting document"):
        _repository(_Connection([_Cursor(rowcount=0)])).save_document(document, manifest)


def test_document_retry_accepts_exact_existing_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _artifact()
    document = _document()
    manifest = build_document_manifest(document, artifact)
    _patch_document_reads(
        monkeypatch,
        artifact=artifact,
        document=document,
        manifest=manifest,
    )
    connection = _Connection([_Cursor(rowcount=0)])

    _repository(connection).save_document(document, manifest)

    assert len(connection.calls) == 1
    assert connection.commits == 1


def test_document_and_manifest_getters_cover_missing_and_found_rows() -> None:
    document = _document()
    artifact = _artifact()
    manifest = build_document_manifest(document, artifact)

    missing_document = _Connection([_Cursor(row=None)])
    assert _repository(missing_document).get_document(_DOCUMENT_ID) is None

    found_document = _Connection(
        [
            _Cursor(row=_document_row(document)),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
        ]
    )
    assert _repository(found_document).get_document(_DOCUMENT_ID) == document

    found_manifest = _Connection([_Cursor(row=(manifest.to_dict(),))])
    missing_manifest = _Connection([_Cursor(row=None)])
    assert _repository(found_manifest).get_manifest(_DOCUMENT_ID) == manifest
    assert _repository(missing_manifest).get_manifest(_DOCUMENT_ID) is None


def test_sections_are_persisted_parent_first_across_multiple_ready_passes() -> None:
    root = Section(_ROOT_SECTION_ID, _DOCUMENT_ID, 1, "Root")
    child = Section(
        _CHILD_SECTION_ID,
        _DOCUMENT_ID,
        0,
        "Child",
        parent_section_id=_ROOT_SECTION_ID,
    )
    document = replace(_document(), sections=(child, root))
    connection = _Connection([])

    PostgresResearchRepository._save_sections(connection, document)

    section_params = [
        params
        for sql, params in connection.calls
        if "INSERT INTO tarkka.section" in sql
    ]
    assert section_params[0] is not None and section_params[0][0] == _ROOT_SECTION_ID
    assert section_params[1] is not None and section_params[1][0] == _CHILD_SECTION_ID


def test_manifest_decoder_rejects_non_object_json() -> None:
    with pytest.raises(RuntimeError, match="must decode to an object"):
        _manifest_from_json([])


def test_query_driver_failure_uses_shared_classifier_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DriverError(Exception):
        pass

    driver = ModuleType("psycopg")
    driver.Error = DriverError
    monkeypatch.setitem(sys.modules, "psycopg", driver)

    original = DriverError("query failed")
    connection = _FailingConnection(original)

    with pytest.raises(PostgresOperationError, match="PostgreSQL operation failed") as raised:
        _repository(connection).get_artifact(_ARTIFACT_ID)

    assert raised.value.__cause__ is original
    assert connection.closed
    assert connection.rollbacks == 1
    assert connection.commits == 0
