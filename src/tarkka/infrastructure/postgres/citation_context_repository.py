"""PostgreSQL persistence for native bibliography references and citation contexts."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from tarkka.domain.citations import BibliographicReference, CitationContext, CitationMention
from tarkka.infrastructure.postgres.connection import (
    PostgresSettings,
    connect,
    translate_driver_error,
)

ConnectionFactory = Callable[[PostgresSettings], Any]


class PostgresCitationConflictError(RuntimeError):
    """Raised when a stable native citation record is reused with changed content."""


class PostgresCitationContextRepository:
    """Immutable persistence for parser-preserved bibliography, mentions, and contexts."""

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save_reference(self, value: BibliographicReference) -> None:
        self._save(
            "bibliographic_reference",
            value.reference_id,
            _reference_params(value),
            value,
            self._get_reference,
        )

    def save_mention(self, value: CitationMention) -> None:
        self._save(
            "citation_mention",
            value.mention_id,
            _mention_params(value),
            value,
            self._get_mention,
        )

    def save_context(self, value: CitationContext) -> None:
        with self._connection() as connection:
            normalized = self._resolve_context_section(connection, value)
            self._save_with_connection(
                connection,
                "citation_context",
                normalized.context_id,
                _context_params(normalized),
                normalized,
                self._get_context,
            )

    def _save(
        self,
        table: str,
        stable_id: UUID,
        params: tuple[object, ...],
        value: object,
        getter: Any,
    ) -> None:
        with self._connection() as connection:
            self._save_with_connection(connection, table, stable_id, params, value, getter)

    @staticmethod
    def _save_with_connection(
        connection: Any,
        table: str,
        stable_id: UUID,
        params: tuple[object, ...],
        value: object,
        getter: Any,
    ) -> None:
        cursor = connection.execute(_INSERTS[table], params)
        if cursor.rowcount == 0:
            existing = getter(connection, stable_id)
            if existing != value:
                raise PostgresCitationConflictError(f"conflicting {table}: {stable_id}")

    @staticmethod
    def _resolve_context_section(connection: Any, value: CitationContext) -> CitationContext:
        if value.section_id is not None or value.passage_id is None:
            return value
        row = connection.execute(
            """SELECT section_id FROM tarkka.passage
            WHERE passage_id = %s AND document_id = %s""",
            (value.passage_id, value.document_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"citation context passage not found: {value.passage_id}")
        return replace(value, section_id=cast(UUID, row[0]))

    def list_references(self, document_id: UUID) -> tuple[BibliographicReference, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                _SELECT_REFERENCE + " WHERE document_id = %s ORDER BY ordinal, reference_id",
                (document_id,),
            ).fetchall()
        return tuple(_reference_from_row(row) for row in rows)

    def list_mentions(self, document_id: UUID) -> tuple[CitationMention, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                _SELECT_MENTION
                + " WHERE document_id = %s"
                + " ORDER BY char_start NULLS LAST, source_anchor NULLS LAST, mention_id",
                (document_id,),
            ).fetchall()
        return tuple(_mention_from_row(row) for row in rows)

    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                _SELECT_CONTEXT + " WHERE document_id = %s ORDER BY char_start, context_id",
                (document_id,),
            ).fetchall()
        return tuple(_context_from_row(row) for row in rows)

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        with self._connection() as connection:
            row = connection.execute(
                _SELECT_CONTEXT + " WHERE document_id = %s AND context_id = %s",
                (document_id, context_id),
            ).fetchone()
        return _context_from_row(row) if row is not None else None

    def list_mentions_for_ids(
        self, document_id: UUID, mention_ids: frozenset[UUID]
    ) -> tuple[CitationMention, ...]:
        if not mention_ids:
            return ()
        placeholders = ", ".join("%s" for _ in mention_ids)
        with self._connection() as connection:
            rows = connection.execute(
                _SELECT_MENTION
                + f" WHERE document_id = %s AND mention_id IN ({placeholders})"
                + " ORDER BY char_start NULLS LAST, source_anchor NULLS LAST, mention_id",
                (document_id, *sorted(mention_ids)),
            ).fetchall()
        return tuple(_mention_from_row(row) for row in rows)

    def count_contexts_for_passages(self, document_id: UUID, passage_ids: frozenset[UUID]) -> int:
        if not passage_ids:
            return 0
        placeholders = ", ".join("%s" for _ in passage_ids)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT count(*) FROM tarkka.citation_context "
                + f"WHERE document_id = %s AND passage_id IN ({placeholders})",
                (document_id, *sorted(passage_ids)),
            ).fetchone()
        return int(cast(tuple[Any, ...], row)[0])

    def list_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[CitationContext, ...]:
        _validate_page(offset, limit)
        if not passage_ids or limit == 0:
            return ()
        query, params = _contexts_for_passages_query(document_id, passage_ids, offset, limit)
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_context_from_row(row) for row in rows)

    def page_contexts_for_passages(
        self,
        document_id: UUID,
        passage_ids: frozenset[UUID],
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[int, tuple[CitationContext, ...]]:
        """Return a page and total from one repeatable-read PostgreSQL snapshot."""
        _validate_page(offset, limit)
        if not passage_ids or limit == 0:
            return 0, ()
        query, params = _contexts_for_passages_query(document_id, passage_ids, offset, limit)
        placeholders = ", ".join("%s" for _ in passage_ids)
        count_query = (
            "SELECT count(*) FROM tarkka.citation_context "
            + f"WHERE document_id = %s AND passage_id IN ({placeholders})"
        )
        count_params = (document_id, *sorted(passage_ids))
        with self._connection() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            total = int(
                cast(tuple[Any, ...], connection.execute(count_query, count_params).fetchone())[0]
            )
            rows = connection.execute(query, params).fetchall()
        return total, tuple(_context_from_row(row) for row in rows)

    @staticmethod
    def _get_reference(connection: Any, stable_id: UUID) -> BibliographicReference | None:
        row = connection.execute(
            _SELECT_REFERENCE + " WHERE reference_id = %s", (stable_id,)
        ).fetchone()
        return _reference_from_row(row) if row is not None else None

    @staticmethod
    def _get_mention(connection: Any, stable_id: UUID) -> CitationMention | None:
        row = connection.execute(
            _SELECT_MENTION + " WHERE mention_id = %s", (stable_id,)
        ).fetchone()
        return _mention_from_row(row) if row is not None else None

    @staticmethod
    def _get_context(connection: Any, stable_id: UUID) -> CitationContext | None:
        row = connection.execute(
            _SELECT_CONTEXT + " WHERE context_id = %s", (stable_id,)
        ).fetchone()
        return _context_from_row(row) if row is not None else None

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


_INSERTS = {
    "bibliographic_reference": """INSERT INTO tarkka.bibliographic_reference (
        reference_id, document_id, ordinal, raw_text, identifiers, title, authors,
        publication_year, source_anchor, source_observation_id
    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s)
    ON CONFLICT (reference_id) DO NOTHING""",
    "citation_mention": """INSERT INTO tarkka.citation_mention (
        mention_id, document_id, reference_id, section_id, passage_id, raw_text,
        char_start, char_end, source_anchor, source_observation_id
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (mention_id) DO NOTHING""",
    "citation_context": """INSERT INTO tarkka.citation_context (
        context_id, mention_id, document_id, section_id, passage_id, text, char_start, char_end
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (context_id) DO NOTHING""",
}
_SELECT_REFERENCE = """SELECT reference_id, document_id, ordinal, raw_text, identifiers, title,
authors, publication_year, source_anchor, source_observation_id
FROM tarkka.bibliographic_reference"""
_SELECT_MENTION = """SELECT mention_id, document_id, raw_text, reference_id, section_id, passage_id,
char_start, char_end, source_anchor, source_observation_id
FROM tarkka.citation_mention"""
_SELECT_CONTEXT = """SELECT context_id, mention_id, document_id, text, char_start, char_end,
section_id, passage_id FROM tarkka.citation_context"""


def _contexts_for_passages_query(
    document_id: UUID,
    passage_ids: frozenset[UUID],
    offset: int,
    limit: int | None,
) -> tuple[str, tuple[object, ...]]:
    placeholders = ", ".join("%s" for _ in passage_ids)
    query = (
        _SELECT_CONTEXT
        + f" WHERE document_id = %s AND passage_id IN ({placeholders})"
        + " ORDER BY char_start, context_id OFFSET %s"
    )
    params: tuple[object, ...] = (document_id, *sorted(passage_ids), offset)
    if limit is not None:
        query += " LIMIT %s"
        params += (limit,)
    return query, params


def _validate_page(offset: int, limit: int | None) -> None:
    if offset < 0:
        raise ValueError("citation context offset must be non-negative")
    if limit is not None and limit < 0:
        raise ValueError("citation context limit must be non-negative")


def _reference_params(value: BibliographicReference) -> tuple[object, ...]:
    return (
        value.reference_id,
        value.document_id,
        value.ordinal,
        value.raw_text,
        json.dumps(dict(value.identifiers), sort_keys=True),
        value.title,
        json.dumps(list(value.authors)),
        value.publication_year,
        value.source_anchor,
        value.source_observation_id,
    )


def _mention_params(value: CitationMention) -> tuple[object, ...]:
    return (
        value.mention_id,
        value.document_id,
        value.reference_id,
        value.section_id,
        value.passage_id,
        value.raw_text,
        value.char_start,
        value.char_end,
        value.source_anchor,
        value.source_observation_id,
    )


def _context_params(value: CitationContext) -> tuple[object, ...]:
    return (
        value.context_id,
        value.mention_id,
        value.document_id,
        value.section_id,
        value.passage_id,
        value.text,
        value.char_start,
        value.char_end,
    )


def _reference_from_row(row: tuple[Any, ...]) -> BibliographicReference:
    return BibliographicReference(
        cast(UUID, row[0]),
        cast(UUID, row[1]),
        int(row[2]),
        cast(str, row[3]),
        _json_object(row[4]),
        cast(str | None, row[5]),
        tuple(_json_array(row[6])),
        cast(int | None, row[7]),
        cast(str | None, row[8]),
        cast(UUID | None, row[9]),
    )


def _mention_from_row(row: tuple[Any, ...]) -> CitationMention:
    return CitationMention(
        cast(UUID, row[0]),
        cast(UUID, row[1]),
        cast(str, row[2]),
        cast(UUID | None, row[3]),
        cast(UUID | None, row[4]),
        cast(UUID | None, row[5]),
        cast(int | None, row[6]),
        cast(int | None, row[7]),
        cast(str | None, row[8]),
        cast(UUID | None, row[9]),
    )


def _context_from_row(row: tuple[Any, ...]) -> CitationContext:
    return CitationContext(
        cast(UUID, row[0]),
        cast(UUID, row[1]),
        cast(UUID, row[2]),
        cast(str, row[3]),
        cast(int, row[4]),
        cast(int, row[5]),
        cast(UUID | None, row[6]),
        cast(UUID | None, row[7]),
    )


def _json_object(value: Any) -> dict[str, str]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("PostgreSQL citation identifiers must decode to an object")
    return decoded


def _json_array(value: Any) -> list[str]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        raise RuntimeError("PostgreSQL citation authors must decode to an array")
    return decoded
