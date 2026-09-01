from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.source_observation_repository import (
    PostgresSourceObservationConflictError,
    PostgresSourceObservationRepository,
    _link_from_row,
    _observation_from_row,
    list_resource_links_for_artifact_with_connection,
)

_OBSERVATION_ID = UUID("00000000-0000-0000-0000-00000000b101")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000b102")
_LINK_ID = UUID("00000000-0000-0000-0000-00000000b103")
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

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def close(self) -> None:
        return None


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=_OBSERVATION_ID,
        source_name="fixture",
        basis=ObservationBasis.NATIVE,
        source_version="1",
        native_artifact_id=_ARTIFACT_ID,
        metadata={"key": "value"},
        observed_at=_OBSERVED_AT,
    )


def _link() -> ResourceLinkObservation:
    return ResourceLinkObservation(
        link_id=_LINK_ID,
        observation_id=_OBSERVATION_ID,
        target_uri="https://example.test/data.csv",
        relation=ResourceRelation.DATASET,
        metadata={"anchor": "data"},
    )


def _observation_row(value: SourceObservation) -> tuple[Any, ...]:
    return (
        value.observation_id,
        value.source_name,
        value.basis.value,
        value.source_version,
        value.provider_record_id,
        value.media_type,
        value.native_artifact_id,
        dict(value.metadata),
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
    return PostgresSourceObservationRepository(
        PostgresSettings("postgresql://unused"), connection_factory=lambda _: connection
    )


def test_postgres_source_observation_rows_round_trip() -> None:
    assert _observation_from_row(_observation_row(_observation())) == _observation()
    assert _link_from_row(_link_row(_link())) == _link()


def test_postgres_source_observation_preserves_first_seen_timestamp() -> None:
    first = _observation()
    later = replace(first, observed_at=datetime(2027, 1, 1, tzinfo=UTC))
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_observation_row(first))])

    _repository(connection).save_observation(later)

    assert "ON CONFLICT (observation_id) DO NOTHING" in connection.calls[0][0]


def test_postgres_source_observation_rejects_changed_stable_content() -> None:
    first = _observation()
    connection = _Connection([_Cursor(rowcount=0), _Cursor(row=_observation_row(first))])

    with pytest.raises(PostgresSourceObservationConflictError, match="conflicting observation"):
        _repository(connection).save_observation(replace(first, metadata={"key": "changed"}))


def test_postgres_source_observation_saves_and_reads_resource_links() -> None:
    observation = _observation()
    link = _link()
    connection = _Connection(
        [
            _Cursor(),
            _Cursor(row=_observation_row(observation)),
            _Cursor(rows=[_link_row(link)]),
            _Cursor(row=_link_row(link)),
        ]
    )
    repository = _repository(connection)

    repository.save_resource_link(link)

    assert repository.get_observation(observation.observation_id) == observation
    assert repository.list_resource_links(observation.observation_id) == (link,)
    assert repository.get_resource_link_for_artifact(_ARTIFACT_ID, link.link_id) == link
    assert "JOIN tarkka.source_observation" in connection.calls[-1][0]


def test_postgres_source_observation_batches_artifact_resource_links() -> None:
    first = _link()
    second = replace(
        first,
        link_id=UUID("00000000-0000-0000-0000-00000000b104"),
        observation_id=UUID("00000000-0000-0000-0000-00000000b105"),
        target_uri="https://example.test/supplement.csv",
    )
    connection = _Connection([_Cursor(rows=[_link_row(first), _link_row(second)])])

    assert list_resource_links_for_artifact_with_connection(connection, _ARTIFACT_ID) == (
        first,
        second,
    )
    assert len(connection.calls) == 1
    query, params = connection.calls[0]
    assert "JOIN tarkka.source_observation" in query
    assert params == (_ARTIFACT_ID,)


def test_postgres_source_observation_pages_resource_links_at_sql_boundary() -> None:
    link = _link()
    connection = _Connection([_Cursor(row=(3,)), _Cursor(rows=[_link_row(link)])])

    total, page = _repository(connection).page_resource_links_for_artifact(
        _ARTIFACT_ID, offset=1, limit=2
    )

    assert (total, page) == (3, (link,))
    assert connection.calls[1][1] == (_ARTIFACT_ID, 1, 2)


def test_postgres_source_observation_rejects_invalid_page_before_connecting() -> None:
    connection = _Connection([])

    with pytest.raises(ValueError, match="non-negative"):
        _repository(connection).page_resource_links_for_artifact(_ARTIFACT_ID, offset=-1, limit=1)

    assert connection.calls == []
