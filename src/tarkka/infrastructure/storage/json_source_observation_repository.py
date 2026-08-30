from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from heapq import nsmallest
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.storage.locking import exclusive_lock


class SourceObservationConflictError(RuntimeError):
    """Raised when a stable observation identity is reused with incompatible content."""


class JsonSourceObservationRepository:
    """Atomic local catalog for source observations and discovered resource links."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"source observation catalog path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write(_empty_catalog())

    @classmethod
    def open_existing(cls, path: Path) -> JsonSourceObservationRepository | None:
        """Open an existing catalog without creating files or lock state."""
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            return None
        if resolved.is_dir():
            raise ValueError(f"source observation catalog path is a directory: {resolved}")
        repository = cls.__new__(cls)
        repository.path = resolved
        return repository

    def save_observation(self, observation: SourceObservation) -> None:
        self._save(
            "observations",
            observation.observation_id,
            _observation_to_dict(observation),
            ignored_fields=frozenset({"observed_at"}),
        )

    def save_resource_link(self, link: ResourceLinkObservation) -> None:
        self._save("resource_links", link.link_id, _resource_link_to_dict(link))

    def get_observation(self, observation_id: UUID) -> SourceObservation | None:
        payload = self._read()["observations"].get(str(observation_id))
        return _observation_from_dict(payload) if payload is not None else None

    def list_resource_links(self, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]:
        values = [
            _resource_link_from_dict(item)
            for item in self._read()["resource_links"].values()
            if item["observation_id"] == str(observation_id)
        ]
        values.sort(key=lambda item: (item.relation.value, item.target_uri, str(item.link_id)))
        return tuple(values)

    def page_resource_links_for_artifact(
        self,
        artifact_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[int, tuple[ResourceLinkObservation, ...]]:
        data = self._read()
        observation_ids = {
            observation_id
            for observation_id, observation in data["observations"].items()
            if observation.get("native_artifact_id") == str(artifact_id)
        }
        if not observation_ids:
            return 0, ()
        total, selected = _bounded_resource_link_payloads(
            data["resource_links"].values(),
            observation_ids=observation_ids,
            offset=offset,
            limit=limit,
        )
        return total, tuple(_resource_link_from_dict(item) for item in selected)

    def page_observations_for_artifact(
        self,
        artifact_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[int, tuple[SourceObservation, ...]]:
        data = self._read()
        values = [
            _observation_from_dict(item)
            for item in data["observations"].values()
            if item.get("native_artifact_id") == str(artifact_id)
        ]
        values.sort(key=lambda item: (item.observed_at, str(item.observation_id)))
        total = len(values)
        return total, tuple(values[offset : offset + limit])

    def _save(
        self,
        collection: str,
        stable_id: UUID,
        payload: dict[str, Any],
        *,
        ignored_fields: frozenset[str] = frozenset(),
    ) -> None:
        key = str(stable_id)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data[collection].get(key)
            if existing is not None:
                if _same_payload(existing, payload, ignored_fields=ignored_fields):
                    return
                raise SourceObservationConflictError(
                    f"conflicting source observation record: {collection}:{key}"
                )
            data[collection][key] = payload
            self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OSError(
                f"unable to read source observation catalog {self.path}: {exc}"
            ) from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid source observation catalog: root must be a JSON object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("unsupported source observation catalog schema version")
        for key in ("observations", "resource_links"):
            if not isinstance(data.get(key), dict):
                raise RuntimeError(f"invalid source observation catalog: {key} must be an object")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".source-observation-", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            _fsync_directory(self.path.parent)
        finally:
            temp_path.unlink(missing_ok=True)


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "observations": {}, "resource_links": {}}


def _observation_to_dict(observation: SourceObservation) -> dict[str, Any]:
    return {
        "observation_id": str(observation.observation_id),
        "source_name": observation.source_name,
        "basis": observation.basis.value,
        "source_version": observation.source_version,
        "provider_record_id": observation.provider_record_id,
        "media_type": observation.media_type,
        "native_artifact_id": (
            str(observation.native_artifact_id)
            if observation.native_artifact_id is not None
            else None
        ),
        "metadata": _json_value(dict(observation.metadata)),
        "observed_at": observation.observed_at.isoformat(),
    }


def _observation_from_dict(payload: Any) -> SourceObservation:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid source observation record")
    return SourceObservation(
        observation_id=UUID(payload["observation_id"]),
        source_name=payload["source_name"],
        basis=ObservationBasis(payload["basis"]),
        source_version=payload.get("source_version"),
        provider_record_id=payload.get("provider_record_id"),
        media_type=payload.get("media_type"),
        native_artifact_id=(
            UUID(payload["native_artifact_id"])
            if payload.get("native_artifact_id") is not None
            else None
        ),
        metadata=payload.get("metadata", {}),
        observed_at=datetime.fromisoformat(payload["observed_at"]),
    )


def _resource_link_to_dict(link: ResourceLinkObservation) -> dict[str, Any]:
    return {
        "link_id": str(link.link_id),
        "observation_id": str(link.observation_id),
        "target_uri": link.target_uri,
        "relation": link.relation.value,
        "media_type": link.media_type,
        "label": link.label,
        "metadata": _json_value(dict(link.metadata)),
    }


def _resource_link_from_dict(payload: Any) -> ResourceLinkObservation:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid resource link observation record")
    return ResourceLinkObservation(
        link_id=UUID(payload["link_id"]),
        observation_id=UUID(payload["observation_id"]),
        target_uri=payload["target_uri"],
        relation=ResourceRelation(payload["relation"]),
        media_type=payload.get("media_type"),
        label=payload.get("label"),
        metadata=payload.get("metadata", {}),
    )


def _same_payload(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    ignored_fields: frozenset[str],
) -> bool:
    keys = (set(left) | set(right)) - ignored_fields
    return all(left.get(key) == right.get(key) for key in keys)


def _bounded_resource_link_payloads(
    values: Any,
    *,
    observation_ids: set[str],
    offset: int,
    limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    selected = [
        item
        for item in values
        if isinstance(item, dict) and item.get("observation_id") in observation_ids
    ]
    total = len(selected)
    if limit <= 0 or offset >= total:
        return total, []
    stop = offset + limit
    ordered = nsmallest(stop, selected, key=_resource_link_sort_key)
    return total, ordered[offset:stop]


def _resource_link_sort_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("relation", "")),
        str(payload.get("target_uri", "")),
        str(payload.get("link_id", "")),
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise ValueError(f"unsupported source observation metadata value: {type(value).__name__}")


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
