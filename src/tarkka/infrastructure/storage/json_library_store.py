"""Local JSON persistence for library catalogs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.application.library import LibraryRecord
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonLibraryStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "libraries": {}})

    def save(self, record: LibraryRecord) -> None:
        with exclusive_lock(self.path):
            data = self._read()
            libraries = cast(dict[str, Any], data["libraries"])
            libraries[str(record.library_id)] = _record_to_dict(record)
            self._write(data)

    def get(self, library_id: UUID) -> LibraryRecord | None:
        with exclusive_lock(self.path):
            payload = cast(dict[str, Any], self._read()["libraries"]).get(str(library_id))
        if payload is None:
            return None
        return _record_from_dict(payload)

    def list_all(self) -> tuple[LibraryRecord, ...]:
        with exclusive_lock(self.path):
            libraries = cast(dict[str, Any], self._read()["libraries"])
        return tuple(_record_from_dict(item) for item in libraries.values())

    def find_for_workspace(self, workspace_id: UUID) -> LibraryRecord | None:
        for record in self.list_all():
            if workspace_id in record.workspace_ids:
                return record
        return None

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read library store {self.path}: {exc}") from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RuntimeError("unsupported library store schema")
        if not isinstance(decoded.get("libraries"), dict):
            raise RuntimeError("invalid library store: libraries must be a JSON object")
        return cast(dict[str, Any], decoded)

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-libraries-", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


def _record_to_dict(record: LibraryRecord) -> dict[str, Any]:
    return {
        "library_id": str(record.library_id),
        "name": record.name,
        "description": record.description,
        "workspace_ids": [str(item) for item in record.workspace_ids],
        "document_ids": [str(item) for item in record.document_ids],
        "claim_ids": [str(item) for item in record.claim_ids],
        "work_ids": [str(item) for item in record.work_ids],
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _record_from_dict(payload: dict[str, Any]) -> LibraryRecord:
    try:
        return LibraryRecord(
            library_id=UUID(payload["library_id"]),
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            workspace_ids=tuple(UUID(item) for item in payload.get("workspace_ids", ())),
            document_ids=tuple(UUID(item) for item in payload.get("document_ids", ())),
            claim_ids=tuple(UUID(item) for item in payload.get("claim_ids", ())),
            work_ids=tuple(UUID(item) for item in payload.get("work_ids", ())),
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid library record: {exc}") from exc
