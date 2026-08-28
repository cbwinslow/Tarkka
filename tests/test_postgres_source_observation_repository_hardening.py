from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings
from tarkka.infrastructure.postgres.source_observation_repository import (
    PostgresSourceObservationConflictError,
    PostgresSourceObservationRepository,
    _json_value,
)

_SETTINGS = PostgresSettings("postgresql://unused")
_OBSERVATION_ID = UUID("00000000-0000-0000-0000-00000000bc01")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000bc02")
_LINK_ID = UUID("00000000-0000-0000-0000-00000000bc03")
_OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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
    commits: int = 0
    rollbacks: int = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: Any) -> None:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        raise self.error


def _observation(*, metadata: dict[str, Any] | None = None) -> SourceObservation:
    return SourceObservation(
        observation_id=_OBSERVATION_ID,
        source_name="fixture",
        basis=ObservationBasis.NATIVE,
        source_version="1",
        provider_record_id="record-1",
        media_type="application/json",
        native_artifact_id=_ARTIFACT_ID,
        metadata={"key": "value"} if metadata is None else metadata,
        observed_at=_OBSERVED_AT,
    )


def _link() -> ResourceLinkObservation:
    return ResourceLinkObservation(
        link_id=_LINK_ID,
        observation_id=_OBSERVATION_ID,
        target_uri="https://example.test/data.csv",
        relation=ResourceRelation.DATASET,
        media_type="text/csv",
        label="Data",
        metadata={"anchor": "dataset"},
    )


def _observation_row(
    value: SourceObservation, *, metadata: Any | None = None
) -> tuple[Any, ...]:
    return (
        value.observation_id,
        value.source_name,
        value.basis.value,
        value.source_version,
        value.provider_record_id,
        value.media_type,
        value.native_artifact_id,
        dict(value.metadata) if metadata is None else metadata,
        value.observed_at,
    )


def _link_row(value: ResourceLinkObservation) -> tuple[Any, ...]:
    return (
        value.link_id,
        value.observation_id,
        value.target_uri,
        value.relation.value,
        value.media_type,
        value.label,
        dict(value.metadata),
    )


def _repository(connection: _Connection) -> PostgresSourceObservationRepository:
    return PostgresSourceObservationRepository(_SETTINGS, connection_factory=lambda _: connection)


def test_fresh_observation_insert_commits_and_closes_connection() -> None:
    connection = _Connection([_Cursor(rowcount=1)])

    _repository(connection).save_observation(_observation())

    assert "INSERT INTO tarkka.source_observation" in connection.calls[0][0]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed


def test_resource_link_retry_accepts_exact_existing_link() -> None:
    link = _link()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_link_row(link))])

    _repository(connection).save_resource_link(link)

    assert "WHERE link_id = %s" in connection.calls[1][0]
    assert connection.commits == 1
    assert connection.rollbacks == 0


@pytest.mark.parametrize("existing_state", ["missing", "changed"])
def test_resource_link_retry_rejects_missing_or_changed_link(existing_state: str) -> None:
    link = _link()
    row = (
        None
        if existing_state == "missing"
        else _link_row(replace(link, target_uri="https://example.test/changed"))
    )
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=row)])

    with pytest.raises(PostgresSourceObservationConflictError, match="conflicting resource link"):
        _repository(connection).save_resource_link(link)

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_list_observations_for_artifact_reconstructs_rows() -> None:
    observation = _observation()
    connection = _Connection([_Cursor(rows=[_observation_row(observation)])])

    assert _repository(connection).list_observations_for_artifact(_ARTIFACT_ID) == (observation,)
    assert connection.calls[0][1] == (_ARTIFACT_ID,)
    assert "ORDER BY source_name, observation_id" in connection.calls[0][0]


def test_resource_link_paging_rejects_negative_limit_before_connecting() -> None:
    connection = _Connection([])

    with pytest.raises(ValueError, match="non-negative"):
        _repository(connection).page_resource_links_for_artifact(
            _ARTIFACT_ID,
            offset=0,
            limit=-1,
        )

    assert connection.calls == []
    assert connection.commits == 0


def test_resource_link_zero_limit_returns_count_without_page_query() -> None:
    connection = _Connection([_Cursor(row=(3,))])

    assert _repository(connection).page_resource_links_for_artifact(
        _ARTIFACT_ID,
        offset=2,
        limit=0,
    ) == (3, ())

    assert len(connection.calls) == 1
    assert "SELECT count(*)" in connection.calls[0][0]
    assert connection.closed


def test_missing_resource_link_for_artifact_returns_none() -> None:
    connection = _Connection([_Cursor(row=None)])

    assert _repository(connection).get_resource_link_for_artifact(_ARTIFACT_ID, _LINK_ID) is None
    assert connection.closed


def test_malformed_database_metadata_fails_closed_and_rolls_back() -> None:
    observation = _observation()
    connection = _Connection([_Cursor(row=_observation_row(observation, metadata="[]"))])

    with pytest.raises(RuntimeError, match="metadata must decode to an object"):
        _repository(connection).get_observation(_OBSERVATION_ID)

    assert connection.closed
    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_nested_metadata_is_thawed_to_jsonb_values() -> None:
    observation = _observation(
        metadata={
            "nested": {"ids": ["a", "b"]},
            "flags": (True, False),
            "score": 1.5,
            "empty": None,
        }
    )
    connection = _Connection([_Cursor(rowcount=1)])

    _repository(connection).save_observation(observation)

    params = connection.calls[0][1]
    assert params is not None
    assert isinstance(params[7], str)
    assert json.loads(params[7]) == {
        "empty": None,
        "flags": [True, False],
        "nested": {"ids": ["a", "b"]},
        "score": 1.5,
    }


def test_json_value_rejects_unsupported_internal_values() -> None:
    with pytest.raises(ValueError, match="unsupported source observation metadata value: object"):
        _json_value(object())


def test_query_driver_failure_uses_shared_classifier_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DriverError(Exception):
        pass

    driver = ModuleType("psycopg")
    driver.Error = DriverError
    monkeypatch.setitem(sys.modules, "psycopg", driver)

    original = DriverError("query failed")
    connection = _FailingConnection(original)

    with pytest.raises(PostgresOperationError, match="PostgreSQL operation failed") as raised:
        _repository(connection).list_observations_for_artifact(_ARTIFACT_ID)

    assert raised.value.__cause__ is original
    assert connection.closed
    assert connection.commits == 0
    assert connection.rollbacks == 1
