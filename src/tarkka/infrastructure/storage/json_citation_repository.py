from __future__ import annotations

import heapq
import json
import os
import tempfile
from collections.abc import Callable
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
            existing_payload = data["resolutions"].get(key)
            if existing_payload == payload:
                return
            if existing_payload is not None:
                existing = _resolution_from_dict(existing_payload)
                if existing.resolution_id != resolution.resolution_id:
                    raise CitationConflictError(
                        f"conflicting resolution identity for reference {resolution.reference_id}"
                    )
                _validate_resolution_transition(existing, resolution)
            data["resolutions"][key] = payload
            self._write(data)

    def save_relation(self, relation: WorkRelation) -> None:
        self._save("relations", relation.relation_id, _relation_to_dict(relation))

    def get_or_create_relation(self, relation: WorkRelation) -> WorkRelation:
        """Atomically persist or reuse one deterministic relation identity."""
        key = str(relation.relation_id)
        payload = _relation_to_dict(relation)
        with exclusive_lock(self.path):
            data = self._read()
            existing_payload = data["relations"].get(key)
            if existing_payload is not None:
                existing = _relation_from_dict(existing_payload)
                if _relation_identity(existing) != _relation_identity(relation):
                    raise CitationConflictError(
                        f"conflicting relation for stable ID {relation.relation_id}"
                    )
                return existing
            data["relations"][key] = payload
            self._write(data)
            return relation

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

    def get_relation(self, relation_id: UUID) -> WorkRelation | None:
        payload = self._read()["relations"].get(str(relation_id))
        return _relation_from_dict(payload) if payload is not None else None

    def list_relations_from(
        self,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None = None,
        exclude_ids: frozenset[UUID] = frozenset(),
        limit: int | None = None,
    ) -> tuple[WorkRelation, ...]:
        return self._relations_matching(
            "subject_work_id",
            work_id,
            kinds=kinds,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    def list_relations_to(
        self,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None = None,
        exclude_ids: frozenset[UUID] = frozenset(),
        limit: int | None = None,
    ) -> tuple[WorkRelation, ...]:
        return self._relations_matching(
            "object_work_id",
            work_id,
            kinds=kinds,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    def _relations_matching(
        self,
        field: str,
        work_id: UUID,
        *,
        kinds: frozenset[WorkRelationKind] | None,
        exclude_ids: frozenset[UUID],
        limit: int | None,
    ) -> tuple[WorkRelation, ...]:
        if limit is not None and limit < 0:
            raise ValueError("relation query limit must be non-negative")
        if limit == 0:
            return ()
        allowed_values = {kind.value for kind in kinds} if kinds is not None else None
        excluded = {str(item) for item in exclude_ids}
        work_key = str(work_id)
        raw_relations = self._read()["relations"].values()
        candidates = (
            _relation_from_dict(item)
            for item in raw_relations
            if item[field] == work_key
            and item["relation_id"] not in excluded
            and (allowed_values is None or item["kind"] in allowed_values)
        )
        if limit is None:
            return tuple(sorted(candidates, key=_relation_sort_key))
        return tuple(heapq.nsmallest(limit, candidates, key=_relation_sort_key))

    def _save(self, bucket: str, stable_id: UUID, payload: dict[str, Any]) -> None:
        key = str(stable_id)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data[bucket].get(key)
            if existing is not None:
                if existing == payload:
                    return
                label = _BUCKET_LABELS[bucket]
                raise CitationConflictError(f"conflicting {label} for stable ID {key}")
            data[bucket][key] = payload
            self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"unable to read citation catalog {self.path}: {exc}") from exc
        try:
            decoded: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid citation catalog JSON {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid citation catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1:
            raise RuntimeError("invalid or unsupported citation catalog")
        for bucket in _BUCKETS:
            entries = data.get(bucket)
            if not isinstance(entries, dict):
                raise RuntimeError(f"invalid citation catalog bucket: {bucket}")
            _validate_bucket_entries(bucket, cast(dict[str, Any], entries))
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-citations-", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            _fsync_directory(self.path.parent)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        finally:
            temp_path.unlink(missing_ok=True)


_BUCKETS = ("references", "mentions", "contexts", "resolutions", "relations")
_BUCKET_LABELS = {
    "references": "reference",
    "mentions": "mention",
    "contexts": "context",
    "resolutions": "resolution",
    "relations": "relation",
}
_BUCKET_IDENTITIES = {
    "references": "reference_id",
    "mentions": "mention_id",
    "contexts": "context_id",
    "resolutions": "reference_id",
    "relations": "relation_id",
}


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, **{bucket: {} for bucket in _BUCKETS}}


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _optional_uuid(value: Any) -> UUID | None:
    return UUID(value) if value is not None else None


def _validate_resolution_transition(
    existing: CitationResolution,
    incoming: CitationResolution,
) -> None:
    if existing.status is not CitationResolutionStatus.RESOLVED:
        return
    if incoming.status is not CitationResolutionStatus.RESOLVED:
        raise CitationConflictError(
            f"resolved citation for reference {existing.reference_id} cannot regress to "
            f"{incoming.status.value}"
        )
    if incoming.work_id != existing.work_id:
        raise CitationConflictError(
            f"resolved citation for reference {existing.reference_id} cannot change canonical work"
        )


def _validate_bucket_entries(bucket: str, entries: dict[str, Any]) -> None:
    parser = _BUCKET_PARSERS[bucket]
    identity_field = _BUCKET_IDENTITIES[bucket]
    for key, payload in entries.items():
        if not isinstance(key, str) or not isinstance(payload, dict):
            raise RuntimeError(f"invalid citation catalog {bucket} entry {key!r}")
        try:
            identity = str(UUID(str(payload[identity_field])))
            if identity != key:
                raise ValueError(f"{identity_field} does not match catalog key")
            parser(cast(dict[str, Any], payload))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"invalid citation catalog {bucket} entry {key!r}: {exc}"
            ) from exc


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


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


def _relation_sort_key(relation: WorkRelation) -> tuple[str, str, str, str]:
    return (
        relation.kind.value,
        str(relation.subject_work_id),
        str(relation.object_work_id),
        str(relation.relation_id),
    )


def _relation_identity(value: WorkRelation) -> tuple[object, ...]:
    return (
        value.relation_id,
        value.subject_work_id,
        value.object_work_id,
        value.kind,
        value.basis,
        value.source_observation_id,
        value.source_document_id,
        value.source_reference_id,
    )


_BUCKET_PARSERS: dict[str, Callable[[dict[str, Any]], object]] = {
    "references": _reference_from_dict,
    "mentions": _mention_from_dict,
    "contexts": _context_from_dict,
    "resolutions": _resolution_from_dict,
    "relations": _relation_from_dict,
}
