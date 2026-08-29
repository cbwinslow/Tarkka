from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import pytest

import tarkka.infrastructure.storage.proof_bundle_snapshot as json_snapshot_module
from tarkka.application.proof_bundles import ProofBundleArtifactNotFoundError
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleSnapshotReader
from tarkka.infrastructure.storage.proof_bundle_snapshot import (
    JsonProofBundleSnapshotReader,
    _ordered_unique_paths,
)
from tests.test_proof_bundles import _ingest_native_document

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_SETTINGS = PostgresSettings("postgresql://unused")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000fb01")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fb02")
_OBSERVATION_ID = UUID("00000000-0000-0000-0000-00000000fb03")
_LINK_ID = UUID("00000000-0000-0000-0000-00000000fb04")
_CREATED_AT = datetime(2026, 8, 29, tzinfo=UTC)


def test_json_snapshot_reads_complete_lineage(tmp_path: Path) -> None:
    result, _, documents, observations = _ingest_native_document(tmp_path)

    snapshot = JsonProofBundleSnapshotReader(
        documents=documents,
        observations=observations,
    ).read(result.document.document_id)

    assert snapshot is not None
    assert snapshot.document == result.document
    assert snapshot.artifact == result.artifact
    assert len(snapshot.work_documents) == 1
    assert len(snapshot.source_observations) == 1
    assert len(snapshot.resource_links) == 1


def test_json_snapshot_handles_unknown_document_and_optional_observations(tmp_path: Path) -> None:
    result, _, documents, _ = _ingest_native_document(tmp_path)
    reader = JsonProofBundleSnapshotReader(documents=documents, observations=None)

    assert reader.read(UUID(int=0)) is None
    snapshot = reader.read(result.document.document_id)

    assert snapshot is not None
    assert snapshot.source_observations == ()
    assert snapshot.resource_links == ()


def test_json_snapshot_fails_closed_if_locked_package_changes_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, documents, observations = _ingest_native_document(tmp_path)
    original_inspect = json_snapshot_module.ResearchPackageService.inspect

    def changed_inspect(self: Any, document_id: UUID) -> Any:
        inspection = original_inspect(self, document_id)
        return inspection.__class__(
            document_id=inspection.document_id,
            artifact_id=UUID(int=1),
            work_documents=inspection.work_documents,
            source_observations=inspection.source_observations,
            resource_links=inspection.resource_links,
        )

    monkeypatch.setattr(json_snapshot_module.ResearchPackageService, "inspect", changed_inspect)

    with pytest.raises(RuntimeError, match="resolved another artifact"):
        JsonProofBundleSnapshotReader(
            documents=documents,
            observations=observations,
        ).read(result.document.document_id)


def test_json_snapshot_acquires_unique_catalog_locks_in_canonical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, documents, observations = _ingest_native_document(tmp_path)
    entered: list[Path] = []
    active: list[Path] = []

    @contextmanager
    def tracking_lock(path: Path) -> Iterator[None]:
        entered.append(path)
        active.append(path)
        try:
            yield
        finally:
            active.remove(path)

    monkeypatch.setattr(json_snapshot_module, "exclusive_lock", tracking_lock)
    snapshot = JsonProofBundleSnapshotReader(
        documents=documents,
        observations=observations,
    ).read(result.document.document_id)

    assert snapshot is not None
    assert entered == sorted(entered, key=str)
    assert len(entered) == 2
    assert active == []
    duplicate = _ordered_unique_paths([documents.path, documents.path, observations.path])
    assert duplicate == tuple(sorted({documents.path, observations.path}, key=str))


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="a" * 64,
        size_bytes=3,
        media_type="text/plain",
        storage_key=PurePosixPath("artifacts/aa/file.txt"),
        original_name="file.txt",
        acquired_at=_CREATED_AT,
        source_uri="https://example.test/file.txt",
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


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[str] = field(default_factory=list)
    closed: bool = False
    commits: int = 0
    rollbacks: int = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        del params
        self.calls.append(sql)
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
        del sql, params
        raise self.error


def _artifact_row() -> tuple[Any, ...]:
    artifact = _artifact()
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


def _document_cursors(document: Document | None) -> list[_Cursor]:
    if document is None:
        return [_Cursor(row=None)]
    return [
        _Cursor(
            row=(
                document.document_id,
                document.artifact_id,
                document.title,
                document.parser_name,
                document.parser_version,
                document.normalized_at,
            )
        ),
        _Cursor(rows=[]),
        _Cursor(rows=[]),
        _Cursor(rows=[]),
        _Cursor(rows=[]),
        _Cursor(rows=[]),
    ]


def _postgres_connection(*, document: Document | None, artifact_present: bool = True) -> _Connection:
    cursors = [_Cursor(), *_document_cursors(document)]
    if document is not None:
        cursors.append(_Cursor(row=_artifact_row() if artifact_present else None))
        if artifact_present:
            cursors.extend(
                [
                    _Cursor(
                        rows=[
                            (
                                _OBSERVATION_ID,
                                "fixture",
                                "native",
                                "1",
                                "record-1",
                                "text/plain",
                                _ARTIFACT_ID,
                                {"source": "fixture"},
                                _CREATED_AT,
                            )
                        ]
                    ),
                    _Cursor(
                        rows=[
                            (
                                _LINK_ID,
                                _OBSERVATION_ID,
                                "https://example.test/supplement",
                                "supplement",
                                "text/csv",
                                "Supplement",
                                {"kind": "data"},
                            )
                        ]
                    ),
                ]
            )
    return _Connection(cursors)


def test_postgres_snapshot_uses_one_repeatable_read_transaction() -> None:
    connection = _postgres_connection(document=_document())
    reader = PostgresProofBundleSnapshotReader(
        _SETTINGS,
        connection_factory=lambda _: connection,
    )

    snapshot = reader.read(_DOCUMENT_ID)

    assert snapshot is not None
    assert snapshot.document == _document()
    assert snapshot.artifact == _artifact()
    assert snapshot.work_documents == ()
    assert len(snapshot.source_observations) == 1
    assert snapshot.source_observations[0].native_artifact_id == _ARTIFACT_ID
    assert len(snapshot.resource_links) == 1
    assert connection.calls[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_postgres_snapshot_unknown_document_returns_none_and_closes() -> None:
    connection = _postgres_connection(document=None)

    result = PostgresProofBundleSnapshotReader(
        _SETTINGS,
        connection_factory=lambda _: connection,
    ).read(_DOCUMENT_ID)

    assert result is None
    assert connection.closed is True


def test_postgres_snapshot_fails_closed_for_missing_artifact() -> None:
    connection = _postgres_connection(document=_document(), artifact_present=False)

    with pytest.raises(ProofBundleArtifactNotFoundError, match="artifact not found"):
        PostgresProofBundleSnapshotReader(
            _SETTINGS,
            connection_factory=lambda _: connection,
        ).read(_DOCUMENT_ID)

    assert connection.rollbacks == 1
    assert connection.closed is True


def test_postgres_snapshot_preserves_untranslated_backend_failures() -> None:
    connection = _FailingConnection(RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        PostgresProofBundleSnapshotReader(
            _SETTINGS,
            connection_factory=lambda _: connection,
        ).read(_DOCUMENT_ID)

    assert connection.closed is True
