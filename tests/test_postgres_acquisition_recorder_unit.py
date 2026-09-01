from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

import tarkka.infrastructure.postgres.connection as connection_module
from tarkka.domain.models import Acquisition
from tarkka.infrastructure.postgres.acquisition_recorder import (
    PostgresAcquisitionRecorder,
    _from_row,
)
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000a201")
_ACQUISITION_ID = UUID("00000000-0000-0000-0000-00000000a202")
_ACQUIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rowcount: int = 1

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


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


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        raise self.error


def _acquisition() -> Acquisition:
    return Acquisition(
        acquisition_id=_ACQUISITION_ID,
        artifact_id=_ARTIFACT_ID,
        source_uri="https://example.test/paper.pdf",
        original_name="paper.pdf",
        acquired_at=_ACQUIRED_AT,
        metadata={"provider": "fixture", "attempt": 1},
    )


def _row(acquisition: Acquisition, *, metadata: object | None = None) -> tuple[Any, ...]:
    return (
        acquisition.acquisition_id,
        acquisition.artifact_id,
        acquisition.source_uri,
        acquisition.acquired_at,
        acquisition.original_name,
        {"provider": "fixture", "attempt": 1} if metadata is None else metadata,
    )


def _recorder(connection: _Connection) -> PostgresAcquisitionRecorder:
    return PostgresAcquisitionRecorder(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )


def test_postgres_acquisition_row_round_trips_mapping_metadata() -> None:
    assert _from_row(_row(_acquisition())) == _acquisition()


def test_postgres_acquisition_row_round_trips_json_metadata() -> None:
    encoded = '{"attempt": 1, "provider": "fixture"}'

    assert _from_row(_row(_acquisition(), metadata=encoded)) == _acquisition()


def test_postgres_acquisition_row_rejects_non_object_metadata() -> None:
    with pytest.raises(RuntimeError, match="metadata must decode to an object"):
        _from_row(_row(_acquisition(), metadata=[]))


def test_postgres_acquisition_recorder_writes_append_only_provenance() -> None:
    connection = _Connection([_Cursor()])

    _recorder(connection).record(_acquisition())

    sql, params = connection.calls[0]
    assert "INSERT INTO tarkka.acquisition" in sql
    assert "ON CONFLICT (acquisition_id) DO NOTHING" in sql
    assert params is not None
    assert params[0] == _ACQUISITION_ID
    assert params[-1] == '{"attempt": 1, "provider": "fixture"}'
    assert connection.closed


def test_postgres_acquisition_recorder_accepts_exact_retry_and_rejects_conflict() -> None:
    acquisition = _acquisition()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_row(acquisition))])
    _recorder(connection).record(acquisition)

    conflicting = replace(acquisition, source_uri="https://example.test/other.pdf")
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_row(acquisition))])
    with pytest.raises(ValueError, match="conflicting acquisition"):
        _recorder(connection).record(conflicting)


def test_postgres_acquisition_recorder_reports_missing_artifact() -> None:
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=None)])

    with pytest.raises(ValueError, match="artifact not found"):
        _recorder(connection).record(_acquisition())


def test_postgres_acquisition_recorder_translates_driver_failure_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("driver disconnected")
    connection = _FailingConnection(original)
    translated = PostgresOperationError("translated")
    monkeypatch.setattr(connection_module, "translate_driver_error", lambda exc: translated)

    with pytest.raises(PostgresOperationError, match="translated") as raised:
        _recorder(connection).record(_acquisition())

    assert raised.value is translated
    assert raised.value.__cause__ is original
    assert connection.closed


def test_postgres_acquisition_recorder_preserves_untranslated_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("application failure")
    connection = _FailingConnection(original)
    monkeypatch.setattr(connection_module, "translate_driver_error", lambda exc: None)

    with pytest.raises(RuntimeError, match="application failure") as raised:
        _recorder(connection).record(_acquisition())

    assert raised.value is original
    assert connection.closed
