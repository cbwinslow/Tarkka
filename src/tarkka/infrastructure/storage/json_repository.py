from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import UUID

from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Artifact, Document, Passage, Section


class JsonResearchRepository:
    """Small local catalog used for the offline reference runtime.

    PostgreSQL remains the reference production system of record. This adapter exists so the core
    vertical slice is runnable without external infrastructure.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"schema_version": 1, "artifacts": {}, "documents": {}})

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read Tarkka catalog {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid Tarkka catalog: root must be a JSON object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("unsupported Tarkka catalog schema version")
        if not isinstance(data.get("artifacts"), dict) or not isinstance(
            data.get("documents"), dict
        ):
            raise RuntimeError("invalid Tarkka catalog: artifacts/documents must be JSON objects")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-catalog-", dir=self.path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)

    def save_artifact(self, artifact: Artifact) -> None:
        data = self._read()
        data["artifacts"][str(artifact.artifact_id)] = _artifact_to_dict(artifact)
        self._write(data)

    def save_document(self, document: Document, manifest: ResourceManifest) -> None:
        data = self._read()
        data["documents"][str(document.document_id)] = {
            "document": _document_to_dict(document),
            "manifest": manifest.to_dict(),
        }
        self._write(data)

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        payload = self._read()["artifacts"].get(str(artifact_id))
        return _artifact_from_dict(payload) if payload else None

    def get_document(self, document_id: UUID) -> Document | None:
        payload = self._read()["documents"].get(str(document_id))
        return _document_from_dict(payload["document"]) if payload else None

    def get_manifest(self, document_id: UUID) -> ResourceManifest | None:
        payload = self._read()["documents"].get(str(document_id))
        if not payload:
            return None
        raw = payload["manifest"]
        return ResourceManifest(
            resource_id=raw["id"],
            kind=raw["kind"],
            title=raw["title"],
            metadata=dict(raw["metadata"]),
            available={key: bool(value) for key, value in raw["available"].items()},
            structure={key: int(value) for key, value in raw["structure"].items()},
            estimated_tokens={key: int(value) for key, value in raw["tokens"].items()},
        )


def _artifact_to_dict(artifact: Artifact) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact.artifact_id),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "media_type": artifact.media_type,
        "storage_key": artifact.storage_key.as_posix(),
        "original_name": artifact.original_name,
        "acquired_at": artifact.acquired_at.isoformat(),
        "source_uri": artifact.source_uri,
    }


def _artifact_from_dict(raw: dict[str, Any]) -> Artifact:
    return Artifact(
        artifact_id=UUID(raw["artifact_id"]),
        sha256=raw["sha256"],
        size_bytes=int(raw["size_bytes"]),
        media_type=raw["media_type"],
        storage_key=PurePosixPath(raw["storage_key"]),
        original_name=raw.get("original_name"),
        acquired_at=datetime.fromisoformat(raw["acquired_at"]),
        source_uri=raw.get("source_uri"),
    )


def _document_to_dict(document: Document) -> dict[str, Any]:
    return {
        "document_id": str(document.document_id),
        "artifact_id": str(document.artifact_id),
        "title": document.title,
        "parser_name": document.parser_name,
        "parser_version": document.parser_version,
        "normalized_at": document.normalized_at.isoformat(),
        "sections": [
            {
                "section_id": str(section.section_id),
                "ordinal": section.ordinal,
                "title": section.title,
                "level": section.level,
                "parent_section_id": (
                    str(section.parent_section_id) if section.parent_section_id else None
                ),
                "passages": [
                    {
                        "passage_id": str(passage.passage_id),
                        "ordinal": passage.ordinal,
                        "text": passage.text,
                        "char_start": passage.char_start,
                        "char_end": passage.char_end,
                    }
                    for passage in section.passages
                ],
            }
            for section in document.sections
        ],
    }


def _document_from_dict(raw: dict[str, Any]) -> Document:
    document_id = UUID(raw["document_id"])
    sections = []
    for section_raw in raw["sections"]:
        section_id = UUID(section_raw["section_id"])
        passages = tuple(
            Passage(
                passage_id=UUID(passage_raw["passage_id"]),
                document_id=document_id,
                section_id=section_id,
                ordinal=int(passage_raw["ordinal"]),
                text=passage_raw["text"],
                char_start=int(passage_raw["char_start"]),
                char_end=int(passage_raw["char_end"]),
            )
            for passage_raw in section_raw["passages"]
        )
        sections.append(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=int(section_raw["ordinal"]),
                title=section_raw["title"],
                level=int(section_raw["level"]),
                parent_section_id=(
                    UUID(section_raw["parent_section_id"])
                    if section_raw.get("parent_section_id")
                    else None
                ),
                passages=passages,
            )
        )
    return Document(
        document_id=document_id,
        artifact_id=UUID(raw["artifact_id"]),
        title=raw["title"],
        parser_name=raw["parser_name"],
        parser_version=raw["parser_version"],
        sections=tuple(sections),
        normalized_at=datetime.fromisoformat(raw["normalized_at"]),
    )
