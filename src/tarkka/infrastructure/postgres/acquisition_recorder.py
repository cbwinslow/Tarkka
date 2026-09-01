"""Append-only PostgreSQL acquisition provenance persistence."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from tarkka.domain.models import Acquisition
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)


class PostgresAcquisitionRecorder:
    """Append immutable acquisition observations after their artifact has been persisted."""

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def record(self, acquisition: Acquisition) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.acquisition (
                    acquisition_id, artifact_id, source_uri, original_name, acquired_at, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (acquisition_id) DO NOTHING
                """,
                (
                    acquisition.acquisition_id,
                    acquisition.artifact_id,
                    acquisition.source_uri,
                    acquisition.original_name,
                    acquisition.acquired_at,
                    json.dumps(dict(acquisition.metadata), sort_keys=True),
                ),
            )
            if cursor.rowcount == 0:
                existing = self._get(connection, acquisition.acquisition_id)
                if existing is None:
                    raise ValueError(
                        f"artifact not found for acquisition: {acquisition.artifact_id}"
                    )
                if existing != acquisition:
                    raise ValueError(f"conflicting acquisition: {acquisition.acquisition_id}")

    @staticmethod
    def _get(connection: Any, acquisition_id: UUID) -> Acquisition | None:
        row = connection.execute(
            """
            SELECT acquisition_id, artifact_id, source_uri, acquired_at, original_name, metadata
            FROM tarkka.acquisition WHERE acquisition_id = %s
            """,
            (acquisition_id,),
        ).fetchone()
        return _from_row(row) if row is not None else None

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            yield connection


def _from_row(row: tuple[Any, ...]) -> Acquisition:
    metadata = json.loads(row[5]) if isinstance(row[5], str) else row[5]
    if not isinstance(metadata, dict):
        raise RuntimeError("PostgreSQL acquisition metadata must decode to an object")
    return Acquisition(
        acquisition_id=row[0],
        artifact_id=row[1],
        source_uri=row[2],
        acquired_at=row[3],
        original_name=row[4],
        metadata=metadata,
    )
