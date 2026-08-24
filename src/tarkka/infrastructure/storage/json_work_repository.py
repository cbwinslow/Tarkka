from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonWorkRepository:
    """Durable local Work catalog for the offline/self-hosted profile."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._transaction_data: dict[str, Any] | None = None
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write(
                    {"schema_version": 1, "works": {}, "identifiers": {}, "source_records": {}}
                )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_data is not None:
            raise RuntimeError("nested Work repository transactions are not supported")
        with exclusive_lock(self.path):
            self._transaction_data = self._read()
            try:
                yield
            except BaseException:
                raise
            else:
                self._write(self._transaction_data)
            finally:
                self._transaction_data = None

    def save_work(self, work: Work) -> None:
        if self._transaction_data is not None:
            self._save_work_into(self._transaction_data, work)
            return
        with exclusive_lock(self.path):
            data = self._read()
            self._save_work_into(data, work)
            self._write(data)

    def get_work(self, work_id: UUID) -> Work | None:
        payload = self._data()["works"].get(str(work_id))
        return _work_from_dict(payload) if payload else None

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        key = _identifier_key(scheme, value)
        payload = self._data()["identifiers"].get(key)
        if not payload:
            return None
        return self.get_work(UUID(payload["work_id"]))

    def save_identifier(self, identifier: WorkIdentifier) -> None:
        key = _identifier_key(identifier.scheme, identifier.value)
        if self._transaction_data is not None:
            self._save_identifier_into(self._transaction_data, key, identifier)
            return
        with exclusive_lock(self.path):
            data = self._read()
            self._save_identifier_into(data, key, identifier)
            self._write(data)

    def list_identifiers(self, work_id: UUID) -> tuple[WorkIdentifier, ...]:
        values = self._data()["identifiers"].values()
        identifiers = (
            _identifier_from_dict(raw)
            for raw in values
            if raw.get("work_id") == str(work_id)
        )
        return tuple(sorted(identifiers, key=lambda item: (item.scheme, item.value)))

    def save_source_record(self, source_record: WorkSourceRecord) -> None:
        key = f"{source_record.provider}:{source_record.provider_id}"
        if self._transaction_data is not None:
            self._save_source_record_into(self._transaction_data, key, source_record)
            return
        with exclusive_lock(self.path):
            data = self._read()
            self._save_source_record_into(data, key, source_record)
            self._write(data)

    def list_source_records(self, work_id: UUID) -> tuple[WorkSourceRecord, ...]:
        values = self._data()["source_records"].values()
        records = (
            _source_record_from_dict(raw)
            for raw in values
            if raw.get("work_id") == str(work_id)
        )
        return tuple(sorted(records, key=lambda item: (item.provider, item.provider_id)))

    def _data(self) -> dict[str, Any]:
        return self._transaction_data if self._transaction_data is not None else self._read()

    @staticmethod
    def _save_work_into(data: dict[str, Any], work: Work) -> None:
        key = str(work.work_id)
        payload = _work_to_dict(work)
        existing = data["works"].get(key)
        if isinstance(existing, dict) and isinstance(existing.get("created_at"), str):
            payload["created_at"] = existing["created_at"]
        data["works"][key] = payload

    @staticmethod
    def _save_identifier_into(
        data: dict[str, Any],
        key: str,
        identifier: WorkIdentifier,
    ) -> None:
        existing = data["identifiers"].get(key)
        if existing:
            if existing["work_id"] != str(identifier.work_id):
                raise ValueError(
                    f"identifier {identifier.scheme}:{identifier.value} belongs to another work"
                )
            return
        data["identifiers"][key] = _identifier_to_dict(identifier)

    @staticmethod
    def _save_source_record_into(
        data: dict[str, Any],
        key: str,
        source_record: WorkSourceRecord,
    ) -> None:
        existing = data["source_records"].get(key)
        if existing and existing["work_id"] != str(source_record.work_id):
            raise ValueError(f"source record {key} belongs to another work")
        data["source_records"][key] = _source_record_to_dict(source_record)

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read Tarkka Work catalog {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid Tarkka Work catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("unsupported Tarkka Work catalog schema version")
        for key in ("works", "identifiers", "source_records"):
            if not isinstance(data.get(key), dict):
                raise RuntimeError(f"invalid Tarkka Work catalog: {key} must be an object")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-works-", dir=self.path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            _fsync_directory(self.path.parent)
        finally:
            temp_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    """Flush an atomic rename where the platform exposes POSIX directory fsync."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _identifier_key(scheme: str, value: str) -> str:
    return f"{scheme.strip().lower()}:{value.strip()}"


def _work_to_dict(work: Work) -> dict[str, Any]:
    return {
        "work_id": str(work.work_id),
        "title": work.title,
        "publication_type": work.publication_type,
        "language": work.language,
        "external_ids": dict(work.external_ids),
        "publication_year": work.publication_year,
        "abstract": work.abstract,
        "venue": work.venue,
        "created_at": work.created_at.isoformat(),
    }


def _work_from_dict(raw: dict[str, Any]) -> Work:
    return Work(
        work_id=UUID(raw["work_id"]),
        title=raw["title"],
        publication_type=raw.get("publication_type", "unknown"),
        language=raw.get("language"),
        external_ids=dict(raw.get("external_ids", {})),
        publication_year=raw.get("publication_year"),
        abstract=raw.get("abstract"),
        venue=raw.get("venue"),
        created_at=datetime.fromisoformat(raw["created_at"]),
    )


def _identifier_to_dict(identifier: WorkIdentifier) -> dict[str, Any]:
    return {
        "identifier_id": str(identifier.identifier_id),
        "work_id": str(identifier.work_id),
        "scheme": identifier.scheme,
        "value": identifier.value,
        "created_at": identifier.created_at.isoformat(),
    }


def _identifier_from_dict(raw: dict[str, Any]) -> WorkIdentifier:
    return WorkIdentifier(
        identifier_id=UUID(raw["identifier_id"]),
        work_id=UUID(raw["work_id"]),
        scheme=raw["scheme"],
        value=raw["value"],
        created_at=datetime.fromisoformat(raw["created_at"]),
    )


def _source_record_to_dict(source_record: WorkSourceRecord) -> dict[str, Any]:
    record = source_record.record
    return {
        "source_record_id": str(source_record.source_record_id),
        "work_id": str(source_record.work_id),
        "observed_at": source_record.observed_at.isoformat(),
        "record": {
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
        },
    }


def _source_record_from_dict(raw: dict[str, Any]) -> WorkSourceRecord:
    record = raw["record"]
    return WorkSourceRecord(
        source_record_id=UUID(raw["source_record_id"]),
        work_id=UUID(raw["work_id"]),
        observed_at=datetime.fromisoformat(raw["observed_at"]),
        record=DiscoveryRecord(
            provider=record["provider"],
            provider_id=record["provider_id"],
            title=record["title"],
            year=record.get("year"),
            doi=record.get("doi"),
            abstract=record.get("abstract"),
            landing_page_url=record.get("landing_page_url"),
            open_access_url=record.get("open_access_url"),
            cited_by_count=record.get("cited_by_count"),
            external_ids=dict(record.get("external_ids", {})),
            metadata=dict(record.get("metadata", {})),
        ),
    )
