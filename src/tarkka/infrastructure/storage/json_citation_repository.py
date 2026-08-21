from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.citations import (
    BibliographicReference,
    CitationContext,
    CitationMention,
    CitationResolution,
    CitationResolutionStatus,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.locking import exclusive_lock


class CitationConflictError(RuntimeError):
    """Raised when a stable citation ID is reused with incompatible content."""


class JsonCitationRepository:
    """Atomic local citation catalog for offline workflows."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"citation catalog path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write(_empty_catalog())

    def save_reference(self, reference: BibliographicReference) -> None:
        self._save("references", reference.reference_id, _reference_to_dict(reference))

    def save_mention(self, mention: CitationMention) -> None:
        self._save("mentions", mention.mention_id, _mention_to_dict(mention))

    def save_context(self, context: CitationContext) -> None:
        self._save("contexts", context.context_id, _context_to_dict(context))

    def save_resolution(self, resolution: CitationResolution) -> None:
        key = str(resolution.reference_id)
        payload = _resolution_to_dict(resolution)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data["resolutions"].get(key)
            if existing == payload:
                return
            if existing is not None and existing.get("resolution_id") != payload["resolution_id"]:
                raise CitationConflictError(
                    f"conflicting resolution identity for reference {resolution.reference_id}"
                )
            data["resolutions"][key] = payload
            self._write(data)

    def save_relation(self, relation: WorkRelation) -> None:
        self._save("relations", relation.relation_id, _relation_to_dict(relation))

    def list_references(self, document_id: UUID) -> tuple[BibliographicReference, ...]:
        values = [
            _reference_from_dict(item)
            for item in self._read()["references"].values()
            if item["document_id"] == str(document_id)
        ]
        values.sort(key=lambda item: (item.ordinal, str(item.reference_id)))
        return tuple(values)

    def list_mentions(self, document_id: UUID) -> tuple[CitationMention, ...]:
        values = [
            _mention_from_dict(item)
            for item in self._read()["mentions"].values()
            if item["document_id"] == str(document_id)
        ]
        values.sort(
            key=lambda item: (
                item.char_start if item.char_start is not None else -1,
                str(item.mention_id),
            )
        )
        return tuple(values)

    def list_contexts(self, document_id: UUID) -> tuple[CitationContext, ...]:
        values = [
            _context_from_dict(item)
            for item in self._read()["contexts"].values()
            if item["document_id"] == str(document_id)
        ]
        values.sort(key=lambda item: (item.char_start, str(item.context_id)))
        return tuple(values)

    def get_resolution(self, reference_id: UUID) -> CitationResolution | None:
        payload = self._read()["resolutions"].get(str(reference_id))
        return _resolution_from_dict(payload) if payload is not None else None

    def list_relations_from(self, work_id: UUID) -> tuple[WorkRelation, ...]:
        return self._relations_matching("subject_work_id", work_id)

    def list_relations_to(self, work_id: UUID) -> tuple[WorkRelation, ...]:
        return self._relations_matching("object_work_id", work_id)

    def _relations_matching(self, field: str, work_id: UUID) -> tuple[WorkRelation, ...]:
        values = [
            _relation_from_dict(item)
            for item in self._read()["relations"].values()
            if item[field] == str(work_id)
        ]
        values.sort(key=lambda item: (item.kind.value, str(item.relation_id)))
        return tuple(values)

    def _save(self, bucket: str, stable_id: UUID, payload: dict[str, Any]) -> None:
        key = str(stable_id)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data[bucket].get(key)
            if existing is not None:
                if existing == payload:
                    return
                raise CitationConflictError(f"conflicting {bucket[:-1]} for stable ID {key}")
            data[bucket][key] = payload
            self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read citation catalog {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid citation catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported citation catalog")
        for bucket in _BUCKETS:
            if bucket not in data or not isinstance(data[bucket], dict):
                raise RuntimeError(f"invalid citation catalog bucket: {bucket}")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-citations-", dir=self.path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)


_BUCKETS = ("references", "mentions", "contexts", "resolutions", "relations")


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, **{bucket: {} for bucket in _BUCKETS}}


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _optional_uuid(value: Any) -> UUID | None:
    return UUID(value) if value is not None else None


def _reference_to_dict(value: BibliographicReference) -> dict[str, Any]:
    return {
        "reference_id": str(value.reference_id),
        "document_id": str(value.document_id),
        "ordinal": value.ordinal,
        "raw_text": value.raw_text,
        "identifiers": dict(value.identifiers),
        "title": value.title,
        "authors": list(value.authors),
        "publication_year": value.publication_year,
        "source_anchor": value.source_anchor,
        "source_observation_id": _uuid(value.source_observation_id),
    }


def _reference_from_dict(raw: dict[str, Any]) -> BibliographicReference:
    return BibliographicReference(
        reference_id=UUID(raw["reference_id"]),
        document_id=UUID(raw["document_id"]),
        ordinal=int(raw["ordinal"]),
        raw_text=raw["raw_text"],
        identifiers=raw.get("identifiers", {}),
        title=raw.get("title"),
        authors=tuple(raw.get("authors", ())),
        publication_year=raw.get("publication_year"),
        source_anchor=raw.get("source_anchor"),
        source_observation_id=_optional_uuid(raw.get("source_observation_id")),
    )


def _mention_to_dict(value: CitationMention) -> dict[str, Any]:
    return {
        "mention_id": str(value.mention_id),
        "document_id": str(value.document_id),
        "raw_text": value.raw_text,
        "reference_id": _uuid(value.reference_id),
        "section_id": _uuid(value.section_id),
        "passage_id": _uuid(value.passage_id),
        "char_start": value.char_start,
        "char_end": value.char_end,
        "source_anchor": value.source_anchor,
        "source_observation_id": _uuid(value.source_observation_id),
    }


def _mention_from_dict(raw: dict[str, Any]) -> CitationMention:
    return CitationMention(
        mention_id=UUID(raw["mention_id"]),
        document_id=UUID(raw["document_id"]),
        raw_text=raw["raw_text"],
        reference_id=_optional_uuid(raw.get("reference_id")),
        section_id=_optional_uuid(raw.get("section_id")),
        passage_id=_optional_uuid(raw.get("passage_id")),
        char_start=raw.get("char_start"),
        char_end=raw.get("char_end"),
        source_anchor=raw.get("source_anchor"),
        source_observation_id=_optional_uuid(raw.get("source_observation_id")),
    )


def _context_to_dict(value: CitationContext) -> dict[str, Any]:
    return {
        "context_id": str(value.context_id),
        "mention_id": str(value.mention_id),
        "document_id": str(value.document_id),
        "text": value.text,
        "char_start": value.char_start,
        "char_end": value.char_end,
        "section_id": _uuid(value.section_id),
        "passage_id": _uuid(value.passage_id),
    }


def _context_from_dict(raw: dict[str, Any]) -> CitationContext:
    return CitationContext(
        context_id=UUID(raw["context_id"]),
        mention_id=UUID(raw["mention_id"]),
        document_id=UUID(raw["document_id"]),
        text=raw["text"],
        char_start=int(raw["char_start"]),
        char_end=int(raw["char_end"]),
        section_id=_optional_uuid(raw.get("section_id")),
        passage_id=_optional_uuid(raw.get("passage_id")),
    )


def _resolution_to_dict(value: CitationResolution) -> dict[str, Any]:
    return {
        "resolution_id": str(value.resolution_id),
        "reference_id": str(value.reference_id),
        "status": value.status.value,
        "work_id": _uuid(value.work_id),
        "candidate_work_ids": [str(item) for item in value.candidate_work_ids],
        "resolver": value.resolver,
        "source_observation_id": _uuid(value.source_observation_id),
        "resolved_at": value.resolved_at.isoformat(),
    }


def _resolution_from_dict(raw: dict[str, Any]) -> CitationResolution:
    return CitationResolution(
        resolution_id=UUID(raw["resolution_id"]),
        reference_id=UUID(raw["reference_id"]),
        status=CitationResolutionStatus(raw["status"]),
        work_id=_optional_uuid(raw.get("work_id")),
        candidate_work_ids=tuple(UUID(item) for item in raw.get("candidate_work_ids", ())),
        resolver=raw.get("resolver"),
        source_observation_id=_optional_uuid(raw.get("source_observation_id")),
        resolved_at=datetime.fromisoformat(raw["resolved_at"]),
    )


def _relation_to_dict(value: WorkRelation) -> dict[str, Any]:
    return {
        "relation_id": str(value.relation_id),
        "subject_work_id": str(value.subject_work_id),
        "object_work_id": str(value.object_work_id),
        "kind": value.kind.value,
        "basis": value.basis.value,
        "source_observation_id": _uuid(value.source_observation_id),
        "source_document_id": _uuid(value.source_document_id),
        "source_reference_id": _uuid(value.source_reference_id),
        "created_at": value.created_at.isoformat(),
    }


def _relation_from_dict(raw: dict[str, Any]) -> WorkRelation:
    return WorkRelation(
        relation_id=UUID(raw["relation_id"]),
        subject_work_id=UUID(raw["subject_work_id"]),
        object_work_id=UUID(raw["object_work_id"]),
        kind=WorkRelationKind(raw["kind"]),
        basis=ObservationBasis(raw["basis"]),
        source_observation_id=_optional_uuid(raw.get("source_observation_id")),
        source_document_id=_optional_uuid(raw.get("source_document_id")),
        source_reference_id=_optional_uuid(raw.get("source_reference_id")),
        created_at=datetime.fromisoformat(raw["created_at"]),
    )
