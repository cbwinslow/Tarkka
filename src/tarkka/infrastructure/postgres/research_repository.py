"""PostgreSQL persistence for normalized source documents and their manifests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID

from tarkka.domain.document_structure import (
    document_sections_parent_first,
    validate_document_structure,
)
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.infrastructure.postgres.connection import (
    PostgresSettings,
    connect,
    translate_driver_error,
)

ConnectionFactory = Callable[[PostgresSettings], Any]


class PostgresResearchRepository:
    """Immutable PostgreSQL implementation of the normalized research-document port.

    Artifacts and normalized documents are content/provenance records, not mutable drafts.
    Repeating the exact write is safe; reusing an identifier for different content is rejected.
    """

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save_artifact(self, artifact: Artifact) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.artifact (
                    artifact_id, sha256, size_bytes, media_type, storage_key,
                    original_name, source_uri, acquired_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    artifact.artifact_id,
                    artifact.sha256,
                    artifact.size_bytes,
                    artifact.media_type,
                    artifact.storage_key.as_posix(),
                    artifact.original_name,
                    artifact.source_uri,
                    artifact.acquired_at,
                ),
            )
            if cursor.rowcount == 0:
                existing = self._get_artifact_by_sha256(connection, artifact.sha256)
                if existing is None or _artifact_identity(existing) != _artifact_identity(artifact):
                    raise ValueError(f"conflicting artifact: {artifact.artifact_id}")

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        with self._connection() as connection:
            return self._get_artifact(connection, artifact_id)

    def save_document(self, document: Document, manifest: ResourceManifest) -> None:
        validate_document_structure(document)
        with self._connection() as connection:
            if self._get_artifact(connection, document.artifact_id) is None:
                raise ValueError(f"artifact not found for document: {document.artifact_id}")
            cursor = connection.execute(
                """
                INSERT INTO tarkka.document (
                    document_id, artifact_id, title, parser_name, parser_version, normalized_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id) DO NOTHING
                """,
                (
                    document.document_id,
                    document.artifact_id,
                    document.title,
                    document.parser_name,
                    document.parser_version,
                    document.normalized_at,
                ),
            )
            if cursor.rowcount == 0:
                existing = self._get_document(connection, document.document_id)
                existing_manifest = self._get_manifest(connection, document.document_id)
                if (
                    existing is None
                    or _document_identity(existing) != _document_identity(document)
                    or existing_manifest != manifest
                ):
                    raise ValueError(f"conflicting document: {document.document_id}")
                return

            self._save_sections(connection, document)
            self._save_source_artifacts(connection, document)
            connection.execute(
                """
                INSERT INTO tarkka.resource_manifest (document_id, manifest)
                VALUES (%s, %s::jsonb)
                """,
                (document.document_id, json.dumps(manifest.to_dict(), sort_keys=True)),
            )

    def get_document(self, document_id: UUID) -> Document | None:
        with self._connection() as connection:
            return self._get_document(connection, document_id)

    def get_manifest(self, document_id: UUID) -> ResourceManifest | None:
        with self._connection() as connection:
            return self._get_manifest(connection, document_id)

    @staticmethod
    def _get_artifact(connection: Any, artifact_id: UUID) -> Artifact | None:
        row = connection.execute(
            """
            SELECT artifact_id, sha256, size_bytes, media_type, storage_key,
                   original_name, acquired_at, source_uri
            FROM tarkka.artifact WHERE artifact_id = %s
            """,
            (artifact_id,),
        ).fetchone()
        return _artifact_from_row(row) if row is not None else None

    @staticmethod
    def _get_artifact_by_sha256(connection: Any, sha256: str) -> Artifact | None:
        row = connection.execute(
            """
            SELECT artifact_id, sha256, size_bytes, media_type, storage_key,
                   original_name, acquired_at, source_uri
            FROM tarkka.artifact WHERE sha256 = %s
            """,
            (sha256,),
        ).fetchone()
        return _artifact_from_row(row) if row is not None else None

    @staticmethod
    def _get_document(connection: Any, document_id: UUID) -> Document | None:
        row = connection.execute(
            """
            SELECT document_id, artifact_id, title, parser_name, parser_version, normalized_at
            FROM tarkka.document WHERE document_id = %s
            """,
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        sections = _sections_from_rows(
            document_id,
            connection.execute(
                """
                SELECT section_id, ordinal, title, level, parent_section_id
                FROM tarkka.section WHERE document_id = %s ORDER BY ordinal
                """,
                (document_id,),
            ).fetchall(),
            connection.execute(
                """
                SELECT passage_id, section_id, ordinal, text, char_start, char_end
                FROM tarkka.passage WHERE document_id = %s ORDER BY section_id, ordinal
                """,
                (document_id,),
            ).fetchall(),
        )
        document = Document(
            document_id=cast(UUID, row[0]),
            artifact_id=cast(UUID, row[1]),
            title=cast(str, row[2]),
            parser_name=cast(str, row[3]),
            parser_version=cast(str, row[4]),
            sections=sections,
            figures=_figures_from_rows(
                connection.execute(
                    """SELECT figure_id, ordinal, page_number, label, caption, figure_type
                FROM tarkka.figure WHERE document_id = %s ORDER BY ordinal""",
                    (document_id,),
                ).fetchall(),
                document_id,
            ),
            tables=_tables_from_rows(
                connection.execute(
                    """SELECT table_id, ordinal, page_number, label, caption,
                       row_count, column_count
                FROM tarkka.document_table WHERE document_id = %s ORDER BY ordinal""",
                    (document_id,),
                ).fetchall(),
                document_id,
            ),
            equations=_equations_from_rows(
                connection.execute(
                    """SELECT equation_id, ordinal, page_number, label, source_text
                FROM tarkka.equation WHERE document_id = %s ORDER BY ordinal""",
                    (document_id,),
                ).fetchall(),
                document_id,
            ),
            normalized_at=cast(datetime, row[5]),
        )
        validate_document_structure(document)
        return document

    @staticmethod
    def _get_manifest(connection: Any, document_id: UUID) -> ResourceManifest | None:
        row = connection.execute(
            "SELECT manifest FROM tarkka.resource_manifest WHERE document_id = %s", (document_id,)
        ).fetchone()
        return _manifest_from_json(row[0]) if row is not None else None

    @staticmethod
    def _save_sections(connection: Any, document: Document) -> None:
        for section in document_sections_parent_first(document):
            connection.execute(
                """
                INSERT INTO tarkka.section (
                    section_id, document_id, parent_section_id, ordinal, level, title
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    section.section_id,
                    document.document_id,
                    section.parent_section_id,
                    section.ordinal,
                    section.level,
                    section.title,
                ),
            )
            for passage in section.passages:
                connection.execute(
                    """
                    INSERT INTO tarkka.passage (
                        passage_id, document_id, section_id, ordinal, text, char_start, char_end
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        passage.passage_id,
                        document.document_id,
                        section.section_id,
                        passage.ordinal,
                        passage.text,
                        passage.char_start,
                        passage.char_end,
                    ),
                )

    @staticmethod
    def _save_source_artifacts(connection: Any, document: Document) -> None:
        for figure in document.figures:
            connection.execute(
                """INSERT INTO tarkka.figure (
                    figure_id, document_id, ordinal, page_number, label, caption, figure_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    figure.figure_id,
                    document.document_id,
                    figure.ordinal,
                    figure.page_number,
                    figure.label,
                    figure.caption,
                    figure.figure_type,
                ),
            )
        for table in document.tables:
            connection.execute(
                """INSERT INTO tarkka.document_table (
                    table_id, document_id, ordinal, page_number, label, caption,
                    row_count, column_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    table.table_id,
                    document.document_id,
                    table.ordinal,
                    table.page_number,
                    table.label,
                    table.caption,
                    table.row_count,
                    table.column_count,
                ),
            )
        for equation in document.equations:
            connection.execute(
                """INSERT INTO tarkka.equation (
                    equation_id, document_id, ordinal, page_number, label, source_text
                ) VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    equation.equation_id,
                    document.document_id,
                    equation.ordinal,
                    equation.page_number,
                    equation.label,
                    equation.source_text,
                ),
            )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        try:
            connection = self._connect(self._settings)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except Exception as exc:
            translated = translate_driver_error(exc)
            if translated is not None:
                raise translated from exc
            raise


def _artifact_from_row(row: tuple[Any, ...]) -> Artifact:
    return Artifact(
        artifact_id=cast(UUID, row[0]),
        sha256=cast(str, row[1]),
        size_bytes=int(row[2]),
        media_type=cast(str, row[3]),
        storage_key=PurePosixPath(cast(str, row[4])),
        original_name=cast(str | None, row[5]),
        acquired_at=cast(datetime, row[6]),
        source_uri=cast(str | None, row[7]),
    )


def _artifact_identity(artifact: Artifact) -> tuple[object, ...]:
    """Content identity deliberately excludes acquisition-specific observations.

    The acquisition table retains where, when, and under which name a byte sequence was observed;
    this canonical artifact row keeps the first such observation for backwards-compatible reads.
    """
    return (
        artifact.artifact_id,
        artifact.sha256,
        artifact.size_bytes,
        artifact.media_type,
        artifact.storage_key,
    )


def _document_identity(document: Document) -> tuple[object, ...]:
    """Normalized content identity deliberately excludes the run timestamp."""
    return (
        document.document_id,
        document.artifact_id,
        document.title,
        document.parser_name,
        document.parser_version,
        document.sections,
        document.figures,
        document.tables,
        document.equations,
    )


def _sections_from_rows(
    document_id: UUID, section_rows: list[tuple[Any, ...]], passage_rows: list[tuple[Any, ...]]
) -> tuple[Section, ...]:
    section_ids = {cast(UUID, row[0]) for row in section_rows}
    if any(cast(UUID, row[1]) not in section_ids for row in passage_rows):
        raise RuntimeError("PostgreSQL passage references section outside document")

    passages_by_section: dict[UUID, list[Passage]] = {}
    for row in passage_rows:
        section_id = cast(UUID, row[1])
        passages_by_section.setdefault(section_id, []).append(
            Passage(
                passage_id=cast(UUID, row[0]),
                document_id=document_id,
                section_id=section_id,
                ordinal=int(row[2]),
                text=cast(str, row[3]),
                char_start=int(row[4]),
                char_end=int(row[5]),
            )
        )
    return tuple(
        Section(
            section_id=cast(UUID, row[0]),
            document_id=document_id,
            ordinal=int(row[1]),
            title=cast(str, row[2]),
            level=int(row[3]),
            parent_section_id=cast(UUID | None, row[4]),
            passages=tuple(passages_by_section.get(cast(UUID, row[0]), [])),
        )
        for row in section_rows
    )


def _figures_from_rows(rows: list[tuple[Any, ...]], document_id: UUID) -> tuple[Figure, ...]:
    return tuple(
        Figure(
            figure_id=cast(UUID, row[0]),
            document_id=document_id,
            ordinal=int(row[1]),
            page_number=cast(int | None, row[2]),
            label=cast(str | None, row[3]),
            caption=cast(str | None, row[4]),
            figure_type=cast(str, row[5]),
        )
        for row in rows
    )


def _tables_from_rows(rows: list[tuple[Any, ...]], document_id: UUID) -> tuple[Table, ...]:
    return tuple(
        Table(
            table_id=cast(UUID, row[0]),
            document_id=document_id,
            ordinal=int(row[1]),
            page_number=cast(int | None, row[2]),
            label=cast(str | None, row[3]),
            caption=cast(str | None, row[4]),
            row_count=cast(int | None, row[5]),
            column_count=cast(int | None, row[6]),
        )
        for row in rows
    )


def _equations_from_rows(rows: list[tuple[Any, ...]], document_id: UUID) -> tuple[Equation, ...]:
    return tuple(
        Equation(
            equation_id=cast(UUID, row[0]),
            document_id=document_id,
            ordinal=int(row[1]),
            page_number=cast(int | None, row[2]),
            label=cast(str | None, row[3]),
            source_text=cast(str | None, row[4]),
        )
        for row in rows
    )


def _manifest_from_json(value: Any) -> ResourceManifest:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("PostgreSQL resource manifest must decode to an object")
    return ResourceManifest(
        resource_id=cast(str, decoded["id"]),
        kind=cast(str, decoded["kind"]),
        title=cast(str, decoded["title"]),
        metadata=dict(cast(dict[str, Any], decoded["metadata"])),
        available={
            key: bool(item) for key, item in cast(dict[str, Any], decoded["available"]).items()
        },
        structure={
            key: int(item) for key, item in cast(dict[str, Any], decoded["structure"]).items()
        },
        estimated_tokens={
            key: int(item) for key, item in cast(dict[str, Any], decoded["tokens"]).items()
        },
    )
