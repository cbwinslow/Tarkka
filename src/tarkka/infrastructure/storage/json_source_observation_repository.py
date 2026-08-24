from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
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
        """Open an existing catalog without creating one for a read-only inspection."""
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            return None
        return cls(resolved)

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

    def list_resource_links(
        self, observation_id: UUID
    ) -> tuple[ResourceLinkObservation, ...]:
        values = [
            _resource_link_from_dict(item)
            for item in self._read()["resource_links"].values()
            if item["observation_id"] == str(observation_id)
        ]
        values.sort(
            key=lambda item: (item.relation.value, item.target_uri, str(item.link_id))
        )
        return tuple(values)

    def list_observations_for_artifact(self, artifact_id: UUID) -> tuple[SourceObservation, ...]:
        values = [
            _observation_from_dict(item)
            for item in self._read()["observations"].values()
            if item.get("native_artifact_id") == str(artifact_id)
        ]
        values.sort(key=lambda item: (item.source_name, str(item.observation_id)))
        return tuple(values)

    def _save(
        self,
        bucket: str,
        stable_id: UUID,
        payload: dict[str, Any],
        *,
        ignored_fields: frozenset[str] = frozenset(),
    ) -> None:
        key = str(stable_id)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data[bucket].get(key)
            if existing is not None:
                if _same_payload(existing, payload, ignored_fields=ignored_fields):
                    # Ignored fields are first-seen metadata and are intentionally preserved.
                    return
                raise SourceObservationConflictError(
                    f"conflicting {bucket} entry for stable ID {key}"
                )
            data[bucket][key] = payload
            self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"unable to read source observation catalog {self.path}: {exc}") from exc
        try:
            decoded: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid source observation catalog JSON {self.path}: {exc}"
            ) from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid source observation catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported source observation catalog")
        for bucket in ("observations", "resource_links"):
            if bucket not in data or not isinstance(data[bucket], dict):
                raise RuntimeError(f"invalid source observation catalog bucket: {bucket}")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=".tarkka-source-observations-",
            dir=self.path.parent,
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "observations": {}, "resource_links": {}}


def _same_payload(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    *,
    ignored_fields: frozenset[str],
) -> bool:
    """Compare stable record content while excluding explicitly first-seen fields."""
    existing_stable = {
        key: value for key, value in existing.items() if key not in ignored_fields
    }
    incoming_stable = {
        key: value for key, value in incoming.items() if key not in ignored_fields
    }
    return existing_stable == incoming_stable


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise ValueError(
        f"unsupported source observation metadata value: {type(value).__name__}"
    )


def _observation_to_dict(value: SourceObservation) -> dict[str, Any]:
    return {
        "observation_id": str(value.observation_id),
        "source_name": value.source_name,
        "basis": value.basis.value,
        "source_version": value.source_version,
        "provider_record_id": value.provider_record_id,
        "media_type": value.media_type,
        "native_artifact_id": (
            str(value.native_artifact_id) if value.native_artifact_id else None
        ),
        "metadata": _json_value(value.metadata),
        "observed_at": value.observed_at.isoformat(),
    }


def _observation_from_dict(raw: dict[str, Any]) -> SourceObservation:
    return SourceObservation(
        observation_id=UUID(raw["observation_id"]),
        source_name=raw["source_name"],
        basis=ObservationBasis(raw["basis"]),
        source_version=raw.get("source_version"),
        provider_record_id=raw.get("provider_record_id"),
        media_type=raw.get("media_type"),
        native_artifact_id=(
            UUID(raw["native_artifact_id"]) if raw.get("native_artifact_id") else None
        ),
        metadata=raw.get("metadata", {}),
        observed_at=datetime.fromisoformat(raw["observed_at"]),
    )


def _resource_link_to_dict(value: ResourceLinkObservation) -> dict[str, Any]:
    return {
        "link_id": str(value.link_id),
        "observation_id": str(value.observation_id),
        "target_uri": value.target_uri,
        "relation": value.relation.value,
        "media_type": value.media_type,
        "label": value.label,
        "metadata": _json_value(value.metadata),
    }


def _resource_link_from_dict(raw: dict[str, Any]) -> ResourceLinkObservation:
    return ResourceLinkObservation(
        link_id=UUID(raw["link_id"]),
        observation_id=UUID(raw["observation_id"]),
        target_uri=raw["target_uri"],
        relation=ResourceRelation(raw["relation"]),
        media_type=raw.get("media_type"),
        label=raw.get("label"),
        metadata=raw.get("metadata", {}),
    )
