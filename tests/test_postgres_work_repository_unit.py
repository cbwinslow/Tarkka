from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.work_repository import (
    PostgresWorkRepository,
    _json_mapping,
    _record_from_json,
    _record_to_dict,
)

_WORK_ID = UUID("00000000-0000-0000-0000-00000000e001")
_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-00000000e002")
_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-00000000e003")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_SETTINGS = PostgresSettings(dsn="postgresql://unused")


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: tuple[tuple[Any, ...], ...] = ()
    rowcount: int = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> tuple[tuple[Any, ...], ...]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)
    closed: bool = False
    entered: int = 0

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        **_: Any,
    ) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        self.entered += 1
        return self

    def __exit__(self, *_: Any) -> None:
        self.entered -= 1

    def close(self) -> None:
        self.closed = True


def _repository(connection: _Connection) -> PostgresWorkRepository:
    return PostgresWorkRepository(_SETTINGS, connection_factory=lambda _: connection)


def _work_row() -> tuple[Any, ...]:
    return (
        _WORK_ID,
        "Evidence-first research",
        "journal-article",
        "en",
        {"doi": "10.1000/example"},
        2026,
        "Abstract",
        "Journal",
        _CREATED_AT,
    )


def _work() -> Work:
    return Work(
        work_id=_WORK_ID,
        title="Evidence-first research",
        publication_type="journal-article",
        language="en",
        external_ids={"doi": "10.1000/example"},
        publication_year=2026,
        abstract="Abstract",
        venue="Journal",
        created_at=_CREATED_AT,
    )


def _identifier() -> WorkIdentifier:
    return WorkIdentifier(
        identifier_id=_IDENTIFIER_ID,
        work_id=_WORK_ID,
        scheme=" DOI ",
        value=" 10.1000/example ",
        created_at=_CREATED_AT,
    )


def _record() -> DiscoveryRecord:
    return DiscoveryRecord(
        provider="openalex",
        provider_id="W123",
        title="Evidence-first research",
        year=2026,
        doi="10.1000/example",
        abstract="Provider abstract",
        landing_page_url="https://example.org/work",
        open_access_url="https://example.org/work.pdf",
        cited_by_count=5,
        external_ids={"doi": "10.1000/example"},
        metadata={"venue": "Journal"},
    )


def _source_record() -> WorkSourceRecord:
    return WorkSourceRecord(
        source_record_id=_SOURCE_RECORD_ID,
        work_id=_WORK_ID,
        record=_record(),
        observed_at=_CREATED_AT,
    )


def test_get_work_decodes_jsonb_and_missing_rows() -> None:
    found_connection = _Connection([_Cursor(row=_work_row())])
    missing_connection = _Connection([_Cursor(row=None)])

    assert _repository(found_connection).get_work(_WORK_ID) == _work()
    assert _repository(missing_connection).get_work(_WORK_ID) is None
    assert found_connection.closed
    assert missing_connection.closed


def test_identifier_lookup_normalizes_scheme_and_reuses_connection() -> None:
    connection = _Connection([_Cursor(row=(_WORK_ID,)), _Cursor(row=_work_row())])

    result = _repository(connection).find_work_by_identifier(" DOI ", " 10.1000/example ")

    assert result == _work()
    assert connection.calls[0][1] == ("doi", "10.1000/example")
    assert len(connection.calls) == 2


def test_identifier_lookup_returns_none_without_second_query() -> None:
    connection = _Connection([_Cursor(row=None)])

    assert _repository(connection).find_work_by_identifier("doi", "missing") is None
    assert len(connection.calls) == 1


def test_identifier_write_normalizes_values_and_translates_ownership_conflict() -> None:
    success = _Connection([_Cursor(rowcount=1)])
    conflict = _Connection([_Cursor(rowcount=0)])

    _repository(success).save_identifier(_identifier())
    assert success.calls[0][1] is not None
    assert success.calls[0][1][2:4] == ("doi", "10.1000/example")

    with pytest.raises(ValueError, match="belongs to another work"):
        _repository(conflict).save_identifier(_identifier())


def test_identifier_listing_reconstructs_domain_objects() -> None:
    row = (_IDENTIFIER_ID, _WORK_ID, "doi", "10.1000/example", _CREATED_AT)
    connection = _Connection([_Cursor(rows=(row,))])

    assert _repository(connection).list_identifiers(_WORK_ID) == (
        WorkIdentifier(
            identifier_id=_IDENTIFIER_ID,
            work_id=_WORK_ID,
            scheme="doi",
            value="10.1000/example",
            created_at=_CREATED_AT,
        ),
    )


def test_source_record_write_and_listing_translate_jsonb() -> None:
    success = _Connection([_Cursor(rowcount=1)])
    record = _source_record()

    _repository(success).save_source_record(record)
    assert success.calls[0][1] is not None
    assert '"provider": "openalex"' in success.calls[0][1][-1]

    listing = _Connection(
        [
            _Cursor(
                rows=(
                    (
                        _SOURCE_RECORD_ID,
                        _WORK_ID,
                        _CREATED_AT,
                        _record_to_dict(record.record),
                    ),
                )
            )
        ]
    )
    assert _repository(listing).list_source_records(_WORK_ID) == (record,)


def test_source_record_write_translates_ownership_conflict() -> None:
    connection = _Connection([_Cursor(rowcount=0)])

    with pytest.raises(ValueError, match="belongs to another work"):
        _repository(connection).save_source_record(_source_record())


def test_transaction_reuses_connection_and_rejects_nesting() -> None:
    connection = _Connection([_Cursor()])
    repository = _repository(connection)

    with repository.transaction():
        repository.save_work(_work())
        with pytest.raises(RuntimeError, match="nested"), repository.transaction():
            pass
        assert not connection.closed

    assert connection.closed
    assert connection.entered == 0


def test_json_helpers_fail_closed_and_round_trip_discovery_records() -> None:
    assert _json_mapping('{"doi": "10.1000/example"}') == {"doi": "10.1000/example"}
    assert _record_from_json(_record_to_dict(_record())) == _record()

    with pytest.raises(RuntimeError, match="decode to an object"):
        _json_mapping([])
    with pytest.raises(RuntimeError, match="string pairs"):
        _json_mapping({"doi": 123})
    with pytest.raises(RuntimeError, match="source record"):
        _record_from_json([])
