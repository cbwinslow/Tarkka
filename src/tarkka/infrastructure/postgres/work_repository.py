from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect

ConnectionFactory = Callable[[PostgresSettings], Any]


class PostgresWorkRepository:
    """PostgreSQL implementation of the canonical Work persistence boundary.

    Active transaction connections are scoped to the current execution context so unrelated
    contexts never share transaction state through a repository instance.
    """

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connection_factory: ConnectionFactory = connect,
    ) -> None:
        self._settings = settings
        self._connect = connection_factory
        self._transaction_connection: ContextVar[Any | None] = ContextVar(
            "tarkka_postgres_work_transaction_connection",
            default=None,
        )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_connection.get() is not None:
            raise RuntimeError("nested Work repository transactions are not supported")
        connection = self._connect(self._settings)
        token = self._transaction_connection.set(connection)
        try:
            with connection:
                yield
        finally:
            self._transaction_connection.reset(token)
            connection.close()

    def save_work(self, work: Work) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO tarkka.work (
                    work_id,
                    title,
                    publication_type,
                    language,
                    external_ids,
                    publication_year,
                    abstract,
                    venue,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (work_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    publication_type = EXCLUDED.publication_type,
                    language = EXCLUDED.language,
                    external_ids = EXCLUDED.external_ids,
                    publication_year = EXCLUDED.publication_year,
                    abstract = EXCLUDED.abstract,
                    venue = EXCLUDED.venue,
                    updated_at = now()
                """,
                (
                    work.work_id,
                    work.title,
                    work.publication_type,
                    work.language,
                    json.dumps(dict(work.external_ids), sort_keys=True),
                    work.publication_year,
                    work.abstract,
                    work.venue,
                    work.created_at,
                ),
            )

    def get_work(self, work_id: UUID) -> Work | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    work_id,
                    title,
                    publication_type,
                    language,
                    external_ids,
                    publication_year,
                    abstract,
                    venue,
                    created_at
                FROM tarkka.work
                WHERE work_id = %s
                """,
                (work_id,),
            ).fetchone()
        return _work_from_row(row) if row is not None else None

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        canonical_scheme = scheme.strip().lower()
        canonical_value = value.strip()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT work_id
                FROM tarkka.work_identifier
                WHERE scheme = %s AND value = %s
                """,
                (canonical_scheme, canonical_value),
            ).fetchone()
            if row is None:
                return None
            return self._get_work(connection, cast(UUID, row[0]))

    def save_identifier(self, identifier: WorkIdentifier) -> None:
        canonical_scheme = identifier.scheme.strip().lower()
        canonical_value = identifier.value.strip()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.work_identifier (
                    identifier_id,
                    work_id,
                    scheme,
                    value,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (scheme, value) DO UPDATE SET
                    work_id = tarkka.work_identifier.work_id
                WHERE tarkka.work_identifier.work_id = EXCLUDED.work_id
                """,
                (
                    identifier.identifier_id,
                    identifier.work_id,
                    canonical_scheme,
                    canonical_value,
                    identifier.created_at,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"identifier {canonical_scheme}:{canonical_value} belongs to another work"
                )

    def list_identifiers(self, work_id: UUID) -> tuple[WorkIdentifier, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT identifier_id, work_id, scheme, value, created_at
                FROM tarkka.work_identifier
                WHERE work_id = %s
                ORDER BY scheme, value
                """,
                (work_id,),
            ).fetchall()
        return tuple(
            WorkIdentifier(
                identifier_id=cast(UUID, row[0]),
                work_id=cast(UUID, row[1]),
                scheme=cast(str, row[2]),
                value=cast(str, row[3]),
                created_at=cast(datetime, row[4]),
            )
            for row in rows
        )

    def save_source_record(self, source_record: WorkSourceRecord) -> None:
        payload = json.dumps(_record_to_dict(source_record.record), sort_keys=True)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tarkka.work_source_record (
                    source_record_id,
                    work_id,
                    provider,
                    provider_record_id,
                    observed_at,
                    record
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (provider, provider_record_id) DO UPDATE SET
                    source_record_id = EXCLUDED.source_record_id,
                    observed_at = EXCLUDED.observed_at,
                    record = EXCLUDED.record
                WHERE tarkka.work_source_record.work_id = EXCLUDED.work_id
                """,
                (
                    source_record.source_record_id,
                    source_record.work_id,
                    source_record.provider,
                    source_record.provider_id,
                    source_record.observed_at,
                    payload,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    "source record "
                    f"{source_record.provider}:{source_record.provider_id} belongs to another work"
                )

    def list_source_records(self, work_id: UUID) -> tuple[WorkSourceRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT source_record_id, work_id, observed_at, record
                FROM tarkka.work_source_record
                WHERE work_id = %s
                ORDER BY provider, provider_record_id
                """,
                (work_id,),
            ).fetchall()
        return tuple(
            WorkSourceRecord(
                source_record_id=cast(UUID, row[0]),
                work_id=cast(UUID, row[1]),
                observed_at=cast(datetime, row[2]),
                record=_record_from_json(row[3]),
            )
            for row in rows
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        transaction_connection = self._transaction_connection.get()
        if transaction_connection is not None:
            yield transaction_connection
            return
        connection = self._connect(self._settings)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _get_work(connection: Any, work_id: UUID) -> Work | None:
        row = connection.execute(
            """
            SELECT
                work_id,
                title,
                publication_type,
                language,
                external_ids,
                publication_year,
                abstract,
                venue,
                created_at
            FROM tarkka.work
            WHERE work_id = %s
            """,
            (work_id,),
        ).fetchone()
        return _work_from_row(row) if row is not None else None


def _work_from_row(row: Any) -> Work:
    return Work(
        work_id=cast(UUID, row[0]),
        title=cast(str, row[1]),
        publication_type=cast(str, row[2]),
        language=cast(str | None, row[3]),
        external_ids=_json_mapping(row[4]),
        publication_year=cast(int | None, row[5]),
        abstract=cast(str | None, row[6]),
        venue=cast(str | None, row[7]),
        created_at=cast(datetime, row[8]),
    )


def _json_mapping(value: Any) -> Mapping[str, str]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("PostgreSQL Work external_ids must decode to an object")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in decoded.items()):
        raise RuntimeError("PostgreSQL Work external_ids must contain string pairs")
    return cast(dict[str, str], decoded)


def _record_to_dict(record: DiscoveryRecord) -> dict[str, Any]:
    return {
        "provider": record.provider,
        "provider_id": record.provider_id,
        "title": record.title,
        "year": record.year,
        "doi": record.doi,
        "abstract": record.abstract,
        "landing_page_url": record.landing_page_url,
        "open_access_url": record.open_access_url,
        "cited_by_count": record.cited_by_count,
        "external_ids": dict(record.external_ids),
        "metadata": dict(record.metadata),
    }


def _record_from_json(value: Any) -> DiscoveryRecord:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("PostgreSQL Work source record must decode to an object")
    raw = cast(dict[str, Any], decoded)
    return DiscoveryRecord(
        provider=cast(str, raw["provider"]),
        provider_id=cast(str, raw["provider_id"]),
        title=cast(str, raw["title"]),
        year=cast(int | None, raw.get("year")),
        doi=cast(str | None, raw.get("doi")),
        abstract=cast(str | None, raw.get("abstract")),
        landing_page_url=cast(str | None, raw.get("landing_page_url")),
        open_access_url=cast(str | None, raw.get("open_access_url")),
        cited_by_count=cast(int | None, raw.get("cited_by_count")),
        external_ids=cast(dict[str, str], dict(raw.get("external_ids", {}))),
        metadata=cast(dict[str, Any], dict(raw.get("metadata", {}))),
    )
