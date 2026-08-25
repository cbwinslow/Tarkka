from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.research_repository import (
    PostgresResearchRepository,
    _artifact_from_row,
    _artifact_identity,
    _document_identity,
    _equations_from_rows,
    _figures_from_rows,
    _manifest_from_json,
    _sections_from_rows,
    _tables_from_rows,
)

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000f101")
_SECTION_ID = UUID("00000000-0000-0000-0000-00000000f102")
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

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _repository(connection: _Connection) -> PostgresResearchRepository:
    return PostgresResearchRepository(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=UUID("00000000-0000-0000-0000-00000000f107"),
        sha256="b" * 64,
        size_bytes=12,
        media_type="text/plain",
        storage_key=PurePosixPath("artifacts/bb/file.txt"),
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
    passage = Passage(
        UUID("00000000-0000-0000-0000-00000000f103"), _DOCUMENT_ID, _SECTION_ID, 0, "Evidence", 0, 8
    )
    return Document(
        document_id=_DOCUMENT_ID,
        artifact_id=_artifact().artifact_id,
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(Section(_SECTION_ID, _DOCUMENT_ID, 0, "Methods", passages=(passage,)),),
        figures=(
            Figure(
                UUID("00000000-0000-0000-0000-00000000f104"),
                _DOCUMENT_ID,
                0,
                2,
                "fig:one",
                "Caption",
                "diagram",
            ),
        ),
        tables=(
            Table(
                UUID("00000000-0000-0000-0000-00000000f105"),
                _DOCUMENT_ID,
                0,
                None,
                None,
                "Table",
                3,
                2,
            ),
        ),
        equations=(
            Equation(
                UUID("00000000-0000-0000-0000-00000000f106"), _DOCUMENT_ID, 0, 3, "eq:one", "E=mc^2"
            ),
        ),
        normalized_at=_CREATED_AT,
    )


def test_postgres_row_deserializers_preserve_document_structure() -> None:
    sections = _sections_from_rows(
        _DOCUMENT_ID,
        [(_SECTION_ID, 0, "Methods", 1, None)],
        [(UUID("00000000-0000-0000-0000-00000000f103"), _SECTION_ID, 0, "Evidence", 0, 8)],
    )

    assert sections[0].passages[0].text == "Evidence"
    assert _figures_from_rows(
        [(UUID("00000000-0000-0000-0000-00000000f104"), 0, 2, "fig:one", "Caption", "diagram")],
        _DOCUMENT_ID,
    ) == (
        Figure(
            UUID("00000000-0000-0000-0000-00000000f104"),
            _DOCUMENT_ID,
            0,
            2,
            "fig:one",
            "Caption",
            "diagram",
        ),
    )
    assert _tables_from_rows(
        [(UUID("00000000-0000-0000-0000-00000000f105"), 0, None, None, "Table", 3, 2)],
        _DOCUMENT_ID,
    ) == (
        Table(
            UUID("00000000-0000-0000-0000-00000000f105"), _DOCUMENT_ID, 0, None, None, "Table", 3, 2
        ),
    )
    assert _equations_from_rows(
        [(UUID("00000000-0000-0000-0000-00000000f106"), 0, 3, "eq:one", "E=mc^2")],
        _DOCUMENT_ID,
    ) == (
        Equation(
            UUID("00000000-0000-0000-0000-00000000f106"), _DOCUMENT_ID, 0, 3, "eq:one", "E=mc^2"
        ),
    )


def test_postgres_serialized_artifact_and_manifest_round_trip() -> None:
    artifact = _artifact()
    assert _artifact_from_row(_artifact_row(artifact)) == artifact
    manifest = _manifest_from_json(
        '{"id":"doc:1","kind":"document","title":"One","metadata":{"x":1},'
        '"available":{"full_text":true},"structure":{"sections":1},"tokens":{"manifest":2}}'
    )
    assert manifest.resource_id == "doc:1"
    assert manifest.metadata == {"x": 1}


def test_postgres_identities_exclude_run_and_acquisition_timestamps() -> None:
    artifact = _artifact()
    document = _document()

    assert _artifact_identity(artifact) == _artifact_identity(
        Artifact(
            artifact_id=artifact.artifact_id,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            media_type=artifact.media_type,
            storage_key=artifact.storage_key,
            original_name="again.txt",
            acquired_at=datetime(2027, 1, 1, tzinfo=UTC),
            source_uri="https://example.test/again.txt",
        )
    )
    assert _document_identity(document) == _document_identity(
        Document(
            document_id=document.document_id,
            artifact_id=document.artifact_id,
            title=document.title,
            parser_name=document.parser_name,
            parser_version=document.parser_version,
            sections=document.sections,
            figures=document.figures,
            tables=document.tables,
            equations=document.equations,
            normalized_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )


def test_postgres_repository_accepts_repeated_content_with_new_acquisition_metadata() -> None:
    artifact = _artifact()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_artifact_row(artifact))])

    _repository(connection).save_artifact(
        Artifact(
            artifact_id=artifact.artifact_id,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            media_type=artifact.media_type,
            storage_key=artifact.storage_key,
            original_name="reacquired.txt",
            acquired_at=datetime(2027, 1, 1, tzinfo=UTC),
            source_uri="https://example.test/reacquired.txt",
        )
    )

    assert "WHERE sha256 = %s" in connection.calls[1][0]


def test_postgres_repository_rejects_missing_and_cyclic_section_parents() -> None:
    artifact = _artifact()
    document = _document()
    missing_parent = UUID("00000000-0000-0000-0000-00000000f199")
    missing_parent_document = replace(
        document,
        sections=(replace(document.sections[0], parent_section_id=missing_parent),),
    )
    cyclic_sections = (
        replace(
            document.sections[0], parent_section_id=UUID("00000000-0000-0000-0000-00000000f198")
        ),
        Section(
            UUID("00000000-0000-0000-0000-00000000f198"),
            document.document_id,
            1,
            "Cycle",
            parent_section_id=document.sections[0].section_id,
        ),
    )
    cyclic_document = replace(document, sections=cyclic_sections)

    for invalid_document in (missing_parent_document, cyclic_document):
        connection = _Connection([_Cursor(row=_artifact_row(artifact)), _Cursor()])
        with pytest.raises(ValueError, match="missing or cyclic parent"):
            _repository(connection).save_document(
                invalid_document, build_document_manifest(invalid_document, artifact)
            )


def test_postgres_repository_writes_complete_immutable_document_graph() -> None:
    artifact = _artifact()
    document = _document()
    manifest = build_document_manifest(document, artifact)
    connection = _Connection([_Cursor(), _Cursor(row=_artifact_row(artifact)), _Cursor()])
    repository = _repository(connection)

    repository.save_artifact(artifact)
    repository.save_document(document, manifest)

    statements = "\n".join(sql for sql, _ in connection.calls)
    assert "INSERT INTO tarkka.artifact" in statements
    assert "INSERT INTO tarkka.document" in statements
    assert "INSERT INTO tarkka.section" in statements
    assert "INSERT INTO tarkka.passage" in statements
    assert "INSERT INTO tarkka.figure" in statements
    assert "INSERT INTO tarkka.document_table" in statements
    assert "INSERT INTO tarkka.equation" in statements
    assert "INSERT INTO tarkka.resource_manifest" in statements
    assert connection.closed


def test_postgres_repository_reconstructs_complete_document_graph() -> None:
    document = _document()
    connection = _Connection(
        [
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
            _Cursor(rows=[(_SECTION_ID, 0, "Methods", 1, None)]),
            _Cursor(
                rows=[
                    (
                        UUID("00000000-0000-0000-0000-00000000f103"),
                        _SECTION_ID,
                        0,
                        "Evidence",
                        0,
                        8,
                    )
                ]
            ),
            _Cursor(
                rows=[
                    (
                        UUID("00000000-0000-0000-0000-00000000f104"),
                        0,
                        2,
                        "fig:one",
                        "Caption",
                        "diagram",
                    )
                ]
            ),
            _Cursor(
                rows=[
                    (
                        UUID("00000000-0000-0000-0000-00000000f105"),
                        0,
                        None,
                        None,
                        "Table",
                        3,
                        2,
                    )
                ]
            ),
            _Cursor(
                rows=[
                    (
                        UUID("00000000-0000-0000-0000-00000000f106"),
                        0,
                        3,
                        "eq:one",
                        "E=mc^2",
                    )
                ]
            ),
        ]
    )

    assert _repository(connection).get_document(document.document_id) == document
