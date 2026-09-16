"""Atomic local JSON storage for opaque cumulative context wallets."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.application.context_wallet import (
    ContextWalletOperation,
    ContextWalletRecord,
    WalletExhaustedError,
)
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonContextWalletStore:
    """A deterministic local adapter that stores no request or research content."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def create(self, record: ContextWalletRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            data = self._read() if self.path.exists() else {"schema_version": 1, "wallets": {}}
            wallets = cast(dict[str, Any], data["wallets"])
            if str(record.wallet_id) in wallets:
                raise RuntimeError("context wallet identifier collision")
            wallets[str(record.wallet_id)] = _record_to_dict(record)
            self._write(data)

    def get(self, wallet_id: UUID) -> ContextWalletRecord | None:
        if not self.path.exists():
            return None
        with exclusive_lock(self.path):
            payload = cast(dict[str, Any], self._read()["wallets"]).get(str(wallet_id))
        return _record_from_dict(payload) if payload is not None else None

    def commit_success(
        self,
        wallet_id: UUID,
        operation_key: str,
        estimated_tokens: int,
        completed_at: datetime,
    ) -> ContextWalletRecord:
        if not self.path.exists():
            raise KeyError(wallet_id)
        with exclusive_lock(self.path):
            data = self._read()
            wallets = cast(dict[str, Any], data["wallets"])
            payload = wallets.get(str(wallet_id))
            if payload is None:
                raise KeyError(wallet_id)
            current = _record_from_dict(payload)
            prior = current.operations.get(operation_key)
            if prior is not None:
                return current
            if estimated_tokens > current.remaining_tokens:
                raise WalletExhaustedError(
                    estimated_tokens=estimated_tokens,
                    max_tokens=current.max_tokens,
                    remaining_tokens=current.remaining_tokens,
                )
            updated = ContextWalletRecord(
                wallet_id=current.wallet_id,
                max_tokens=current.max_tokens,
                consumed_tokens=current.consumed_tokens + estimated_tokens,
                created_at=current.created_at,
                updated_at=completed_at,
                operations={
                    **current.operations,
                    operation_key: ContextWalletOperation(
                        estimated_tokens=estimated_tokens,
                        consumed_tokens=current.consumed_tokens + estimated_tokens,
                        completed_at=completed_at,
                    ),
                },
            )
            wallets[str(wallet_id)] = _record_to_dict(updated)
            self._write(data)
            return updated

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read context wallet store {self.path}: {exc}") from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RuntimeError("unsupported context wallet store schema")
        if not isinstance(decoded.get("wallets"), dict):
            raise RuntimeError("invalid context wallet store: wallets must be a JSON object")
        return cast(dict[str, Any], decoded)

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-context-wallets-", dir=self.path.parent)
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


def _record_to_dict(record: ContextWalletRecord) -> dict[str, object]:
    return {
        "wallet_id": str(record.wallet_id),
        "max_tokens": record.max_tokens,
        "consumed_tokens": record.consumed_tokens,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "operations": {
            key: {
                "estimated_tokens": operation.estimated_tokens,
                "consumed_tokens": operation.consumed_tokens,
                "completed_at": operation.completed_at.isoformat(),
            }
            for key, operation in record.operations.items()
        },
    }


def _record_from_dict(payload: object) -> ContextWalletRecord:
    try:
        if not isinstance(payload, dict):
            raise TypeError("wallet record must be a JSON object")
        operations_payload = payload.get("operations", {})
        if not isinstance(operations_payload, dict):
            raise TypeError("wallet operations must be a JSON object")
        operations = {
            str(key): _operation_from_dict(value) for key, value in operations_payload.items()
        }
        return ContextWalletRecord(
            wallet_id=UUID(str(payload.get("wallet_id", ""))),
            max_tokens=int(payload["max_tokens"]),
            consumed_tokens=int(payload["consumed_tokens"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
            operations=operations,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid context wallet record: {exc}") from exc


def _operation_from_dict(payload: object) -> ContextWalletOperation:
    if not isinstance(payload, dict):
        raise TypeError("wallet operation must be a JSON object")
    return ContextWalletOperation(
        estimated_tokens=int(payload["estimated_tokens"]),
        consumed_tokens=int(payload["consumed_tokens"]),
        completed_at=datetime.fromisoformat(str(payload["completed_at"])),
    )
