from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.citations import BibliographicReference, CitationContext, CitationMention
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationConflictError,
    PostgresCitationContextRepository,
    _context_from_row,
    _mention_from_row,
    _reference_from_row,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000c801")
_REFERENCE_ID = UUID("00000000-0000-0000-0000-00000000c802")
_MENTION_ID = UUID("00000000-0000-0000-0000-00000000c803")
_CONTEXT_ID = UUID("00000000-0000-0000-0000-00000000c804")
_OBSERVATION_ID = UUID("00000000-0000-0000-0000-00000000c805")


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


def _reference() -> BibliographicReference:
    return BibliographicReference(
        _REFERENCE_ID,
        _DOCUMENT_ID,
        0,
        "A. Author. Evidence first.",
        {"doi": "10.1000/example"},
        "Evidence first",
        ("A. Author",),
        2026,
        "ref-1",
        _OBSERVATION_ID,
    )


def _mention() -> CitationMention:
    return CitationMention(
        _MENTION_ID,
        _DOCUMENT_ID,
        "[1]",
        _REFERENCE_ID,
        None,
        None,
        4,
        7,
        "cite-1",
        _OBSERVATION_ID,
    )


def _context() -> CitationContext:
    return CitationContext(_CONTEXT_ID, _MENTION_ID, _DOCUMENT_ID, "cite [1]", 0, 8)


def _reference_row(value: BibliographicReference) -> tuple[Any, ...]:
    return (
        value.reference_id,
        value.document_id,
        value.ordinal,
        value.raw_text,
        dict(value.identifiers),
        value.title,
        list(value.authors),
        value.publication_year,
        value.source_anchor,
        value.source_observation_id,
    )


def _mention_row(value: CitationMention) -> tuple[Any, ...]:
    return (
        value.mention_id,
        value.document_id,
        value.raw_text,
        value.reference_id,
        value.section_id,
        value.passage_id,
        value.char_start,
        value.char_end,
        value.source_anchor,
        value.source_observation_id,
    )


def _context_row(value: CitationContext) -> tuple[Any, ...]:
    return (
        value.context_id,
        value.mention_id,
        value.document_id,
        value.text,
        value.char_start,
        value.char_end,
        value.section_id,
        value.passage_id,
    )


def _repository(connection: _Connection) -> PostgresCitationContextRepository:
    return PostgresCitationContextRepository(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )


def test_postgres_native_citation_rows_round_trip() -> None:
    assert _reference_from_row(_reference_row(_reference())) == _reference()
    assert _mention_from_row(_mention_row(_mention())) == _mention()
    assert _context_from_row(_context_row(_context())) == _context()


def test_postgres_native_citation_repository_writes_and_lists_records() -> None:
    reference = _reference()
    mention = _mention()
    context = _context()
    connection = _Connection(
        [
            _Cursor(),
            _Cursor(),
            _Cursor(),
            _Cursor(rows=[_reference_row(reference)]),
            _Cursor(rows=[_mention_row(mention)]),
            _Cursor(rows=[_context_row(context)]),
        ]
    )
    repository = _repository(connection)

    repository.save_reference(reference)
    repository.save_mention(mention)
    repository.save_context(context)

    assert repository.list_references(_DOCUMENT_ID) == (reference,)
    assert repository.list_mentions(_DOCUMENT_ID) == (mention,)
    assert repository.list_contexts(_DOCUMENT_ID) == (context,)
    assert "ON CONFLICT (reference_id) DO NOTHING" in connection.calls[0][0]
    assert "NULLS LAST" in connection.calls[4][0]
    assert connection.closed


def test_postgres_native_citation_repository_rejects_conflicting_stable_ids() -> None:
    reference = _reference()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_reference_row(reference))])

    with pytest.raises(PostgresCitationConflictError, match="bibliographic_reference"):
        _repository(connection).save_reference(replace(reference, raw_text="different"))


def test_postgres_native_citation_repository_reads_conflict_targets() -> None:
    reference = _reference()
    mention = _mention()
    context = _context()
    connection = _Connection(
        [
            _Cursor(row=_reference_row(reference)),
            _Cursor(row=_mention_row(mention)),
            _Cursor(row=_context_row(context)),
        ]
    )

    assert PostgresCitationContextRepository._get_reference(connection, _REFERENCE_ID) == reference
    assert PostgresCitationContextRepository._get_mention(connection, _MENTION_ID) == mention
    assert PostgresCitationContextRepository._get_context(connection, _CONTEXT_ID) == context


def test_postgres_native_citation_repository_derives_context_section_from_passage() -> None:
    passage_id = UUID("00000000-0000-0000-0000-00000000c806")
    section_id = UUID("00000000-0000-0000-0000-00000000c807")
    context = replace(_context(), passage_id=passage_id)
    connection = _Connection([_Cursor(row=(section_id,)), _Cursor()])

    _repository(connection).save_context(context)

    assert connection.calls[0][1] == (passage_id, _DOCUMENT_ID)
    assert connection.calls[1][1] is not None
    assert connection.calls[1][1][3] == section_id


def test_postgres_native_citation_repository_rejects_missing_context_passage() -> None:
    context = replace(_context(), passage_id=UUID("00000000-0000-0000-0000-00000000c806"))
    connection = _Connection([_Cursor(row=None)])

    with pytest.raises(ValueError, match="passage not found"):
        _repository(connection).save_context(context)


def test_postgres_native_citation_repository_rejects_invalid_json_shapes() -> None:
    with pytest.raises(RuntimeError, match="identifiers"):
        _reference_from_row(
            (*_reference_row(_reference())[:4], [], *_reference_row(_reference())[5:])
        )
    with pytest.raises(RuntimeError, match="authors"):
        _reference_from_row(
            (
                *_reference_row(_reference())[:6],
                {"not": "an array"},
                *_reference_row(_reference())[7:],
            )
        )


def test_postgres_citation_repository_supports_verification_context_reads() -> None:
    mention = _mention()
    context = replace(_context(), passage_id=UUID("00000000-0000-0000-0000-00000000c806"))
    passage_id = context.passage_id
    assert passage_id is not None
    connection = _Connection(
        [
            _Cursor(row=_context_row(context)),
            _Cursor(rows=[_mention_row(mention)]),
            _Cursor(row=(1,)),
            _Cursor(rows=[_context_row(context)]),
            _Cursor(),
            _Cursor(row=(1,)),
            _Cursor(rows=[_context_row(context)]),
        ]
    )
    repository = _repository(connection)

    assert repository.get_context(_DOCUMENT_ID, _CONTEXT_ID) == context
    assert repository.list_mentions_for_ids(_DOCUMENT_ID, frozenset((_MENTION_ID,))) == (mention,)
    assert repository.list_mentions_for_ids(_DOCUMENT_ID, frozenset()) == ()
    assert repository.count_contexts_for_passages(_DOCUMENT_ID, frozenset((passage_id,))) == 1
    assert repository.count_contexts_for_passages(_DOCUMENT_ID, frozenset()) == 0
    assert repository.list_contexts_for_passages(
        _DOCUMENT_ID, frozenset((passage_id,)), offset=1, limit=2
    ) == (context,)
    assert repository.page_contexts_for_passages(
        _DOCUMENT_ID, frozenset((passage_id,)), offset=1, limit=2
    ) == (1, (context,))
    assert connection.calls[4][0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"


@pytest.mark.parametrize(("offset", "limit"), [(-1, None), (0, -1)])
def test_postgres_citation_repository_rejects_invalid_context_pagination(
    offset: int, limit: int | None
) -> None:
    with pytest.raises(ValueError, match="citation context"):
        _repository(_Connection([])).list_contexts_for_passages(
            _DOCUMENT_ID, frozenset((_MENTION_ID,)), offset=offset, limit=limit
        )
