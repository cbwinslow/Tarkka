"""Local JSON persistence for workspace records."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.application.workspace import (
    WorkspaceMode,
    WorkspaceQuestion,
    WorkspaceRecord,
)
from tarkka.domain.models import Workspace
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonWorkspaceStore:
    """Store workspaces beside the local Tarkka home catalog."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "workspaces": {}})

    def save(self, record: WorkspaceRecord) -> None:
        with exclusive_lock(self.path):
            data = self._read()
            workspaces = cast(dict[str, Any], data["workspaces"])
            workspaces[str(record.workspace.workspace_id)] = _record_to_dict(record)
            self._write(data)

    def get(self, workspace_id: UUID) -> WorkspaceRecord | None:
        with exclusive_lock(self.path):
            payload = cast(dict[str, Any], self._read()["workspaces"]).get(str(workspace_id))
        if payload is None:
            return None
        return _record_from_dict(payload)

    def find_by_name(self, name: str) -> WorkspaceRecord | None:
        with exclusive_lock(self.path):
            workspaces = cast(dict[str, Any], self._read()["workspaces"])
        for payload in workspaces.values():
            record = _record_from_dict(payload)
            if record.workspace.name == name:
                return record
        return None

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read workspace store {self.path}: {exc}") from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RuntimeError("unsupported workspace store schema")
        if not isinstance(decoded.get("workspaces"), dict):
            raise RuntimeError("invalid workspace store: workspaces must be a JSON object")
        return cast(dict[str, Any], decoded)

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-workspaces-", dir=self.path.parent)
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


def _record_to_dict(record: WorkspaceRecord) -> dict[str, Any]:
    workspace = record.workspace
    return {
        "workspace": {
            "workspace_id": str(workspace.workspace_id),
            "name": workspace.name,
            "description": workspace.description,
            "domain_pack": workspace.domain_pack,
            "created_at": workspace.created_at.isoformat(),
            "settings": dict(workspace.settings),
        },
        "spec_digest": record.spec_digest,
        "questions": [
            {
                "question_id": question.question_id,
                "text": question.text,
                "subtopics": list(question.subtopics),
            }
            for question in record.questions
        ],
        "mode": record.mode.value,
        "warnings": list(record.warnings),
        "document_ids": [str(item) for item in record.document_ids],
        "claim_ids": [str(item) for item in record.claim_ids],
        "updated_at": record.updated_at.isoformat(),
    }


def _record_from_dict(payload: MappingLike) -> WorkspaceRecord:
    workspace_payload = payload["workspace"]
    return WorkspaceRecord(
        workspace=Workspace(
            workspace_id=UUID(workspace_payload["workspace_id"]),
            name=workspace_payload["name"],
            description=workspace_payload.get("description", ""),
            domain_pack=workspace_payload.get("domain_pack"),
            created_at=datetime.fromisoformat(workspace_payload["created_at"]),
            settings=workspace_payload.get("settings") or {},
        ),
        spec_digest=payload["spec_digest"],
        questions=tuple(
            WorkspaceQuestion(
                question_id=str(item["question_id"]),
                text=str(item["text"]),
                subtopics=tuple(str(part) for part in item.get("subtopics", ())),
            )
            for item in payload.get("questions", ())
        ),
        mode=WorkspaceMode(payload.get("mode", "frozen")),
        warnings=tuple(str(item) for item in payload.get("warnings", ())),
        document_ids=tuple(UUID(item) for item in payload.get("document_ids", ())),
        claim_ids=tuple(UUID(item) for item in payload.get("claim_ids", ())),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
    )


MappingLike = dict[str, Any]
