from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.extraction import HumanReviewState
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.storage.locking import exclusive_lock


class VerificationConflictError(RuntimeError):
    """A stable evidence-relation ID was reused with incompatible content."""


class JsonVerificationRepository:
    """Atomic local store for immutable evidence-verification assessments."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"verification catalog path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "relations": {}})

    @classmethod
    def open_existing(cls, path: Path) -> JsonVerificationRepository | None:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            return None
        if resolved.is_dir():
            raise ValueError(f"verification catalog path is a directory: {resolved}")
        repository = cls.__new__(cls)
        repository.path = resolved
        return repository

    def save_relation(self, relation: EvidenceRelation) -> None:
        key = str(relation.relation_id)
        payload = _to_dict(relation)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data["relations"].get(key)
            if existing is not None:
                if _same_relation(existing, payload):
                    return
                raise VerificationConflictError(
                    f"conflicting evidence relation: {relation.relation_id}"
                )
            data["relations"][key] = payload
            self._write(data)

    def get_relation(self, relation_id: UUID) -> EvidenceRelation | None:
        raw = self._read()["relations"].get(str(relation_id))
        return _from_dict(raw) if raw is not None else None

    def count_relations(self, claim_id: UUID) -> int:
        return sum(item["claim_id"] == str(claim_id) for item in self._read()["relations"].values())

    def list_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[EvidenceRelation, ...]:
        if offset < 0 or limit < 0:
            raise ValueError("verification offset and limit must be non-negative")
        values = [
            _from_dict(item)
            for item in self._read()["relations"].values()
            if item["claim_id"] == str(claim_id)
        ]
        values.sort(key=lambda item: str(item.relation_id))
        return tuple(values[offset : offset + limit])

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read verification catalog {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid verification catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported verification catalog")
        relations = data.get("relations")
        if not isinstance(relations, dict):
            raise RuntimeError("invalid verification catalog bucket: relations")
        _validate_relation_entries(cast(dict[str, Any], relations))
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-verifications-", dir=self.path.parent)
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


def _to_dict(value: EvidenceRelation) -> dict[str, Any]:
    return {
        "relation_id": str(value.relation_id), "claim_id": str(value.claim_id),
        "kind": value.kind.value, "verifier_name": value.verifier_name,
        "verifier_version": value.verifier_version, "confidence": value.confidence,
        "human_review_state": value.human_review_state.value,
        "evidence_id": str(value.evidence_id) if value.evidence_id is not None else None,
        "citation_context_id": (
            str(value.citation_context_id) if value.citation_context_id is not None else None
        ),
        "reasoning_summary": value.reasoning_summary, "created_at": value.created_at.isoformat(),
    }


def _from_dict(raw: dict[str, Any]) -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=UUID(raw["relation_id"]), claim_id=UUID(raw["claim_id"]),
        kind=EvidenceRelationKind(raw["kind"]), verifier_name=raw["verifier_name"],
        verifier_version=raw["verifier_version"], confidence=float(raw["confidence"]),
        human_review_state=HumanReviewState(raw["human_review_state"]),
        evidence_id=UUID(raw["evidence_id"]) if raw.get("evidence_id") else None,
        citation_context_id=(
            UUID(raw["citation_context_id"]) if raw.get("citation_context_id") else None
        ),
        reasoning_summary=raw.get("reasoning_summary"),
        created_at=datetime.fromisoformat(raw["created_at"]),
    )


def _same_relation(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {key: value for key, value in left.items() if key != "created_at"} == {
        key: value for key, value in right.items() if key != "created_at"
    }


def _validate_relation_entries(entries: dict[str, Any]) -> None:
    for key, payload in entries.items():
        if not isinstance(key, str) or not isinstance(payload, dict):
            raise RuntimeError(f"invalid verification catalog relation entry {key!r}")
        try:
            relation = _from_dict(cast(dict[str, Any], payload))
            if str(relation.relation_id) != key:
                raise ValueError("relation_id does not match catalog key")
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"invalid verification catalog relation entry {key!r}: {exc}"
            ) from exc


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
