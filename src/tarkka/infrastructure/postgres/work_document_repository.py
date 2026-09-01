"""PostgreSQL persistence for canonical Work-to-Document representation links."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)


class PostgresWorkDocumentRepository:
    """PostgreSQL implementation of the canonical Work representation-link port."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connection_factory: ConnectionFactory = connect,
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save_work_document_link(self, link: WorkDocumentLink) -> None:
        """Persist one immutable link, treating an identical repeated write as idempotent."""
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.work_document_link (
                    link_id,
                    work_id,
                    artifact_id,
                    document_id,
                    linked_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (link_id) DO UPDATE SET
                    link_id = tarkka.work_document_link.link_id
                WHERE tarkka.work_document_link.work_id = EXCLUDED.work_id
                  AND tarkka.work_document_link.artifact_id = EXCLUDED.artifact_id
                  AND tarkka.work_document_link.document_id = EXCLUDED.document_id
                """,
                (
                    link.link_id,
                    link.work_id,
                    link.artifact_id,
                    link.document_id,
                    link.linked_at,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"conflicting work document link: {link.link_id}")

    def list_work_document_links(self, work_id: UUID) -> tuple[WorkDocumentLink, ...]:
        with self._connection() as connection:
            return list_work_document_links_with_connection(connection, work_id)

    def list_document_work_links(self, document_id: UUID) -> tuple[WorkDocumentLink, ...]:
        with self._connection() as connection:
            return list_document_work_links_with_connection(connection, document_id)

    @staticmethod
    def _list_work_document_links(
        connection: Any,
        work_id: UUID,
    ) -> tuple[WorkDocumentLink, ...]:
        return list_work_document_links_with_connection(connection, work_id)

    @staticmethod
    def _list_document_work_links(
        connection: Any,
        document_id: UUID,
    ) -> tuple[WorkDocumentLink, ...]:
        return list_document_work_links_with_connection(connection, document_id)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            yield connection


def list_work_document_links_with_connection(
    connection: Any,
    work_id: UUID,
) -> tuple[WorkDocumentLink, ...]:
    """Read Work representation links through a caller-owned PostgreSQL connection."""
    rows = connection.execute(
        """
        SELECT link_id, work_id, artifact_id, document_id, linked_at
        FROM tarkka.work_document_link
        WHERE work_id = %s
        ORDER BY link_id
        """,
        (work_id,),
    ).fetchall()
    return _work_document_links_from_rows(rows)


def list_document_work_links_with_connection(
    connection: Any,
    document_id: UUID,
) -> tuple[WorkDocumentLink, ...]:
    """Read Document representation links through a caller-owned PostgreSQL connection."""
    rows = connection.execute(
        """
        SELECT link_id, work_id, artifact_id, document_id, linked_at
        FROM tarkka.work_document_link
        WHERE document_id = %s
        ORDER BY link_id
        """,
        (document_id,),
    ).fetchall()
    return _work_document_links_from_rows(rows)


def _work_document_links_from_rows(rows: list[tuple[Any, ...]]) -> tuple[WorkDocumentLink, ...]:
    return tuple(
        WorkDocumentLink(
            link_id=cast(UUID, row[0]),
            work_id=cast(UUID, row[1]),
            artifact_id=cast(UUID, row[2]),
            document_id=cast(UUID, row[3]),
            linked_at=cast(datetime, row[4]),
        )
        for row in rows
    )
