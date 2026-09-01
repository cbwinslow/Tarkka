"""PostgreSQL persistence for immutable saved document context-package handles."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from tarkka.domain.context_packages import SavedDocumentContextPackage
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)


class PostgresDocumentContextPackageRepository:
    """Reference store for immutable, exact document-section selections."""

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save(self, package: SavedDocumentContextPackage) -> None:
        with self._connection() as connection:
            if not self._document_exists(connection, package.document_id):
                raise ValueError(f"document not found for context package: {package.document_id}")
            if not self._sections_belong_to_document(
                connection, package.document_id, package.section_ids
            ):
                raise ValueError("context package sections do not belong to its document")
            cursor = connection.execute(
                """
                INSERT INTO tarkka.document_context_package (
                    context_package_id, document_id, estimated_tokens, created_at
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (context_package_id) DO NOTHING
                """,
                (
                    package.context_package_id,
                    package.document_id,
                    package.estimated_tokens,
                    package.created_at,
                ),
            )
            if cursor.rowcount == 0:
                existing = self._get(connection, package.context_package_id)
                if existing is None or _identity(existing) != _identity(package):
                    raise ValueError(f"conflicting context package: {package.context_package_id}")
                return
            for ordinal, section_id in enumerate(package.section_ids):
                connection.execute(
                    """
                    INSERT INTO tarkka.document_context_package_section (
                        context_package_id, document_id, section_id, ordinal
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (package.context_package_id, package.document_id, section_id, ordinal),
                )
            connection.execute(
                """
                UPDATE tarkka.document_context_package
                SET is_finalized = true
                WHERE context_package_id = %s
                """,
                (package.context_package_id,),
            )

    def get(self, context_package_id: UUID) -> SavedDocumentContextPackage | None:
        with self._connection() as connection:
            return self._get(connection, context_package_id)

    @staticmethod
    def _document_exists(connection: Any, document_id: UUID) -> bool:
        return connection.execute(
            "SELECT 1 FROM tarkka.document WHERE document_id = %s", (document_id,)
        ).fetchone() is not None

    @staticmethod
    def _sections_belong_to_document(
        connection: Any, document_id: UUID, section_ids: tuple[UUID, ...]
    ) -> bool:
        rows = connection.execute(
            """
            SELECT section_id
            FROM tarkka.section
            WHERE document_id = %s AND section_id = ANY(%s)
            """,
            (document_id, list(section_ids)),
        ).fetchall()
        return len(rows) == len(section_ids)

    @staticmethod
    def _get(connection: Any, context_package_id: UUID) -> SavedDocumentContextPackage | None:
        header = connection.execute(
            """
            SELECT context_package_id, document_id, estimated_tokens, created_at
            FROM tarkka.document_context_package
            WHERE context_package_id = %s AND is_finalized = true
            """,
            (context_package_id,),
        ).fetchone()
        if header is None:
            return None
        section_rows = connection.execute(
            """
            SELECT section_id
            FROM tarkka.document_context_package_section
            WHERE context_package_id = %s
            ORDER BY ordinal
            """,
            (context_package_id,),
        ).fetchall()
        return SavedDocumentContextPackage(
            context_package_id=cast(UUID, header[0]),
            document_id=cast(UUID, header[1]),
            section_ids=tuple(cast(UUID, row[0]) for row in section_rows),
            estimated_tokens=cast(int, header[2]),
            created_at=cast(datetime, header[3]),
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            yield connection


def _identity(value: SavedDocumentContextPackage) -> tuple[object, ...]:
    return value.document_id, value.section_ids, value.estimated_tokens
