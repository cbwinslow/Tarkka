"""Atomic local persistence for immutable document context-package selections."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.context_packages import SavedDocumentContextPackage
from tarkka.infrastructure.storage.locking import exclusive_lock


class ContextPackageConflictError(RuntimeError):
    """A stable context-package ID was reused with incompatible content."""


class JsonDocumentContextPackageRepository:
    """Durable local store; PostgreSQL remains the production system of record."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"context-package catalog path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "packages": {}})

    def save(self, package: SavedDocumentContextPackage) -> None:
        key = str(package.context_package_id)
        payload = _to_dict(package)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data["packages"].get(key)
            if existing is not None:
                if _same_package(existing, payload):
                    return
                raise ContextPackageConflictError(f"conflicting context package: {key}")
            data["packages"][key] = payload
            self._write(data)

    def get(self, context_package_id: UUID) -> SavedDocumentContextPackage | None:
        raw = self._read()["packages"].get(str(context_package_id))
        return _from_dict(raw) if raw is not None else None

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"unable to read context-package catalog {self.path}: {exc}"
            ) from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported context-package catalog")
        packages = decoded.get("packages")
        if not isinstance(packages, dict):
            raise RuntimeError("invalid context-package catalog bucket: packages")
        for key, payload in packages.items():
            if not isinstance(key, str) or not isinstance(payload, dict):
                raise RuntimeError(f"invalid context-package catalog entry {key!r}")
            try:
                package = _from_dict(cast(dict[str, Any], payload))
                if str(package.context_package_id) != key:
                    raise ValueError("context_package_id does not match catalog key")
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"invalid context-package catalog entry {key!r}: {exc}") from exc
        return cast(dict[str, Any], decoded)

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-context-packages-", dir=self.path.parent)
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


def _to_dict(package: SavedDocumentContextPackage) -> dict[str, Any]:
    return {
        "context_package_id": str(package.context_package_id),
        "document_id": str(package.document_id),
        "section_ids": [str(section_id) for section_id in package.section_ids],
        "estimated_tokens": package.estimated_tokens,
        "created_at": package.created_at.isoformat(),
    }


def _from_dict(raw: dict[str, Any]) -> SavedDocumentContextPackage:
    section_ids = raw["section_ids"]
    if not isinstance(section_ids, list) or any(
        not isinstance(value, str) for value in section_ids
    ):
        raise TypeError("section_ids must be a list of UUID strings")
    estimated_tokens = raw["estimated_tokens"]
    if isinstance(estimated_tokens, bool) or not isinstance(estimated_tokens, int):
        raise TypeError("estimated_tokens must be an integer")
    return SavedDocumentContextPackage(
        context_package_id=UUID(raw["context_package_id"]),
        document_id=UUID(raw["document_id"]),
        section_ids=tuple(UUID(value) for value in section_ids),
        estimated_tokens=estimated_tokens,
        created_at=datetime.fromisoformat(raw["created_at"]),
    )


def _same_package(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {key: value for key, value in left.items() if key != "created_at"} == {
        key: value for key, value in right.items() if key != "created_at"
    }


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
