from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from tarkka.domain.crawl_access import RobotsFetchOutcome, RobotsFetchResult
from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.robots_cache import RobotsCacheEntry
from tarkka.infrastructure.storage.locking import exclusive_lock


class RobotsCacheConflictError(RuntimeError):
    """Raised when cache history would be rolled back or rewritten ambiguously."""


class JsonRobotsCache:
    """Atomic local latest-entry cache for bounded robots policy fetches."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"robots cache path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write(_empty_catalog())

    def get(self, robots_uri: str) -> RobotsCacheEntry | None:
        key = normalize_http_uri(robots_uri, field_name="robots cache URI")
        payload = self._read()["entries"].get(key)
        return _entry_from_dict(payload) if payload is not None else None

    def save(self, entry: RobotsCacheEntry) -> None:
        if not isinstance(entry, RobotsCacheEntry):
            raise ValueError("robots cache entry must be a RobotsCacheEntry")
        key = entry.robots_uri
        payload = _entry_to_dict(entry)
        with exclusive_lock(self.path):
            data = self._read()
            existing_payload = data["entries"].get(key)
            if existing_payload is not None:
                existing = _entry_from_dict(existing_payload)
                if entry.fetched_at < existing.fetched_at:
                    raise RobotsCacheConflictError("robots cache cannot roll back to an older fetch")
                if entry.fetched_at == existing.fetched_at:
                    if payload == existing_payload:
                        return
                    raise RobotsCacheConflictError(
                        "conflicting robots cache entries share the same fetch time"
                    )
            data["entries"][key] = payload
            self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"unable to read robots cache {self.path}: {exc}") from exc
        try:
            decoded: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid robots cache JSON {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid robots cache: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported robots cache schema")
        if not isinstance(data.get("entries"), dict):
            raise RuntimeError("invalid robots cache: entries must be an object")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-robots-cache-", dir=self.path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "entries": {}}


def _entry_to_dict(entry: RobotsCacheEntry) -> dict[str, Any]:
    return {
        "robots_uri": entry.robots_uri,
        "outcome": entry.result.outcome.value,
        "content": entry.result.content,
        "status_code": entry.result.status_code,
        "fetched_at": entry.fetched_at.isoformat(),
        "expires_at": entry.expires_at.isoformat(),
    }


def _entry_from_dict(raw: dict[str, Any]) -> RobotsCacheEntry:
    if not isinstance(raw, dict):
        raise RuntimeError("invalid robots cache entry: record must be an object")
    try:
        result = RobotsFetchResult(
            robots_uri=raw["robots_uri"],
            outcome=RobotsFetchOutcome(raw["outcome"]),
            content=raw.get("content"),
            status_code=raw.get("status_code"),
        )
        fetched_at = datetime.fromisoformat(raw["fetched_at"])
        expires_at = datetime.fromisoformat(raw["expires_at"])
        return RobotsCacheEntry(
            result=result,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid robots cache entry: {exc}") from exc
