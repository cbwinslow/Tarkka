"""PostgreSQL persistence for immutable source observations and resource links."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.postgres.connection import (
    ConnectionFactory,
    PostgresSettings,
    connect,
    managed_connection,
)


class PostgresSourceObservationConflictError(RuntimeError):
    """Raised when a stable source-observation ID is reused with changed content."""


class PostgresSourceObservationRepository:
    """Immutable PostgreSQL source-observation repository with bounded artifact queries."""

    def __init__(
        self, settings: PostgresSettings, *, connection_factory: ConnectionFactory = connect
    ) -> None:
        self._settings = settings
        self._connect = connection_factory

    def save_observation(self, observation: SourceObservation) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO tarkka.source_observation (
                    observation_id, source_name, basis, source_version, provider_record_id,
                    media_type, native_artifact_id, metadata, observed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (observation_id) DO NOTHING""",
                _observation_params(observation),
            )
            if cursor.rowcount == 0:
                existing = self._get_observation(connection, observation.observation_id)
                if existing is None or _observation_identity(existing) != _observation_identity(
                    observation
                ):
                    raise PostgresSourceObservationConflictError(
                        f"conflicting observation: {observation.observation_id}"
                    )

    def save_resource_link(self, link: ResourceLinkObservation) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO tarkka.resource_link_observation (
                    link_id, observation_id, target_uri, resource_relation, media_type,
                    link_label, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (link_id) DO NOTHING""",
                _link_params(link),
            )
            if cursor.rowcount == 0:
                existing = self._get_resource_link(connection, link.link_id)
                if existing != link:
                    raise PostgresSourceObservationConflictError(
                        f"conflicting resource link: {link.link_id}"
                    )

    def get_observation(self, observation_id: UUID) -> SourceObservation | None:
        with self._connection() as connection:
            return self._get_observation(connection, observation_id)

    def list_resource_links(self, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]:
        with self._connection() as connection:
            return list_resource_links_with_connection(connection, observation_id)

    def list_observations_for_artifact(self, artifact_id: UUID) -> tuple[SourceObservation, ...]:
        with self._connection() as connection:
            return list_observations_for_artifact_with_connection(connection, artifact_id)

    def page_resource_links_for_artifact(
        self, artifact_id: UUID, *, offset: int, limit: int
    ) -> tuple[int, tuple[ResourceLinkObservation, ...]]:
        if offset < 0 or limit < 0:
            raise ValueError("resource link offset and limit must be non-negative")
        with self._connection() as connection:
            count = connection.execute(
                """SELECT count(*)
                FROM tarkka.resource_link_observation AS link
                JOIN tarkka.source_observation AS observation
                  ON observation.observation_id = link.observation_id
                WHERE observation.native_artifact_id = %s""",
                (artifact_id,),
            ).fetchone()
            if limit == 0:
                return int(cast(tuple[Any, ...], count)[0]), ()
            rows = connection.execute(
                _SELECT_LINKS
                + """ JOIN tarkka.source_observation AS observation
                       ON observation.observation_id = resource_link_observation.observation_id
                    WHERE observation.native_artifact_id = %s
                    ORDER BY resource_relation, target_uri, link_id OFFSET %s LIMIT %s""",
                (artifact_id, offset, limit),
            ).fetchall()
        return int(cast(tuple[Any, ...], count)[0]), tuple(_link_from_row(row) for row in rows)

    def get_resource_link_for_artifact(
        self, artifact_id: UUID, link_id: UUID
    ) -> ResourceLinkObservation | None:
        with self._connection() as connection:
            row = connection.execute(
                _SELECT_LINKS
                + """ JOIN tarkka.source_observation AS observation
                       ON observation.observation_id = resource_link_observation.observation_id
                    WHERE observation.native_artifact_id = %s AND link_id = %s""",
                (artifact_id, link_id),
            ).fetchone()
        return _link_from_row(row) if row is not None else None

    @staticmethod
    def _get_observation(connection: Any, observation_id: UUID) -> SourceObservation | None:
        row = connection.execute(
            _SELECT_OBSERVATIONS + " WHERE observation_id = %s", (observation_id,)
        ).fetchone()
        return _observation_from_row(row) if row is not None else None

    @staticmethod
    def _get_resource_link(connection: Any, link_id: UUID) -> ResourceLinkObservation | None:
        row = connection.execute(_SELECT_LINKS + " WHERE link_id = %s", (link_id,)).fetchone()
        return _link_from_row(row) if row is not None else None

    @staticmethod
    def _list_resource_links(
        connection: Any, observation_id: UUID
    ) -> tuple[ResourceLinkObservation, ...]:
        return list_resource_links_with_connection(connection, observation_id)

    @staticmethod
    def _list_observations_for_artifact(
        connection: Any, artifact_id: UUID
    ) -> tuple[SourceObservation, ...]:
        return list_observations_for_artifact_with_connection(connection, artifact_id)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with managed_connection(
            self._settings,
            connection_factory=self._connect,
        ) as connection:
            yield connection


def list_resource_links_with_connection(
    connection: Any,
    observation_id: UUID,
) -> tuple[ResourceLinkObservation, ...]:
    """Read one observation's resource links on a caller-owned PostgreSQL connection."""
    rows = connection.execute(
        _SELECT_LINKS
        + " WHERE observation_id = %s ORDER BY resource_relation, target_uri, link_id",
        (observation_id,),
    ).fetchall()
    return tuple(_link_from_row(row) for row in rows)


def list_observations_for_artifact_with_connection(
    connection: Any,
    artifact_id: UUID,
) -> tuple[SourceObservation, ...]:
    """Read Artifact observations through a caller-owned PostgreSQL connection."""
    rows = connection.execute(
        _SELECT_OBSERVATIONS
        + " WHERE native_artifact_id = %s ORDER BY source_name, observation_id",
        (artifact_id,),
    ).fetchall()
    return tuple(_observation_from_row(row) for row in rows)


_SELECT_OBSERVATIONS = """SELECT observation_id, source_name, basis, source_version,
provider_record_id, media_type, native_artifact_id, metadata, observed_at
FROM tarkka.source_observation"""
_SELECT_LINKS = """SELECT resource_link_observation.link_id,
resource_link_observation.observation_id, resource_link_observation.target_uri,
resource_link_observation.resource_relation, resource_link_observation.media_type,
resource_link_observation.link_label, resource_link_observation.metadata
FROM tarkka.resource_link_observation"""


def _observation_params(value: SourceObservation) -> tuple[object, ...]:
    return (
        value.observation_id,
        value.source_name,
        value.basis.value,
        value.source_version,
        value.provider_record_id,
        value.media_type,
        value.native_artifact_id,
        json.dumps(_json_value(value.metadata), sort_keys=True),
        value.observed_at,
    )


def _link_params(value: ResourceLinkObservation) -> tuple[object, ...]:
    return (
        value.link_id,
        value.observation_id,
        value.target_uri,
        value.relation.value,
        value.media_type,
        value.label,
        json.dumps(_json_value(value.metadata), sort_keys=True),
    )


def _observation_from_row(row: tuple[Any, ...]) -> SourceObservation:
    return SourceObservation(
        observation_id=cast(UUID, row[0]),
        source_name=cast(str, row[1]),
        basis=ObservationBasis(cast(str, row[2])),
        source_version=cast(str | None, row[3]),
        provider_record_id=cast(str | None, row[4]),
        media_type=cast(str | None, row[5]),
        native_artifact_id=cast(UUID | None, row[6]),
        metadata=_json_object(row[7]),
        observed_at=cast(datetime, row[8]),
    )


def _link_from_row(row: tuple[Any, ...]) -> ResourceLinkObservation:
    return ResourceLinkObservation(
        link_id=cast(UUID, row[0]),
        observation_id=cast(UUID, row[1]),
        target_uri=cast(str, row[2]),
        relation=ResourceRelation(cast(str, row[3])),
        media_type=cast(str | None, row[4]),
        label=cast(str | None, row[5]),
        metadata=_json_object(row[6]),
    )


def _json_object(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("PostgreSQL source observation metadata must decode to an object")
    return decoded


def _json_value(value: Any) -> Any:
    """Thaw validated source metadata into values accepted by PostgreSQL JSONB."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise ValueError(f"unsupported source observation metadata value: {type(value).__name__}")


def _observation_identity(value: SourceObservation) -> tuple[object, ...]:
    return (
        value.observation_id,
        value.source_name,
        value.basis,
        value.source_version,
        value.provider_record_id,
        value.media_type,
        value.native_artifact_id,
        value.metadata,
    )
