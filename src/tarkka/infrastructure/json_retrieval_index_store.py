"""Atomic JSON storage for complete retrieval-segment index snapshots."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.infrastructure.storage.locking import exclusive_lock
from tarkka.ports.retrieval_indexes import RetrievalSegmentStore


class JsonRetrievalSegmentStore(RetrievalSegmentStore):
    """Persist complete derived indexes in a separate atomic catalog."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "indexes": {}})

    def replace(self, index: RetrievalSegmentIndex) -> None:
        with exclusive_lock(self.path):
            data = self._read()
            data["indexes"][_key(index)] = _to_dict(index)
            self._write(data)

    def get(
        self, *, document_id: UUID, derivation_version: str, configuration_fingerprint: str
    ) -> RetrievalSegmentIndex | None:
        raw = self._read()["indexes"].get(
            _key_parts(document_id, derivation_version, configuration_fingerprint)
        )
        return _from_dict(raw) if raw is not None else None

    def list_for_document(self, document_id: UUID) -> tuple[RetrievalSegmentIndex, ...]:
        return tuple(
            sorted(
                (
                    _from_dict(value)
                    for value in self._read()["indexes"].values()
                    if value["document_id"] == str(document_id)
                ),
                key=lambda item: (item.derivation_version, item.configuration_fingerprint),
            )
        )

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data.get("indexes"), dict):
                raise ValueError("unsupported catalog")
            return cast(dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read retrieval index catalog: {exc}") from exc

    def _write(self, data: dict[str, Any]) -> None:
        fd, name = tempfile.mkstemp(prefix=".tarkka-retrieval-", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def _key(index: RetrievalSegmentIndex) -> str:
    return _key_parts(index.document_id, index.derivation_version, index.configuration_fingerprint)


def _key_parts(document_id: UUID, derivation_version: str, configuration_fingerprint: str) -> str:
    return "|".join((str(document_id), derivation_version, configuration_fingerprint))


def _to_dict(index: RetrievalSegmentIndex) -> dict[str, Any]:
    return {
        "document_id": str(index.document_id),
        "derivation_version": index.derivation_version,
        "configuration_fingerprint": index.configuration_fingerprint,
        "segments": [
            {
                "document_id": str(segment.document_id),
                "text": segment.text,
                "derivation_version": segment.derivation_version,
                "configuration_fingerprint": segment.configuration_fingerprint,
                "spans": [
                    {
                        "section_id": str(span.section_id),
                        "passage_id": str(span.passage_id),
                        "char_start": span.char_start,
                        "char_end": span.char_end,
                    }
                    for span in segment.source_spans
                ],
            }
            for segment in index.segments
        ],
    }


def _from_dict(raw: dict[str, Any]) -> RetrievalSegmentIndex:
    segments = tuple(
        RetrievalSegment(
            document_id=UUID(value["document_id"]),
            text=value["text"],
            source_spans=tuple(
                RetrievalPassageSpan(
                    UUID(span["section_id"]),
                    UUID(span["passage_id"]),
                    span["char_start"],
                    span["char_end"],
                )
                for span in value["spans"]
            ),
            derivation_version=value["derivation_version"],
            configuration_fingerprint=value["configuration_fingerprint"],
        )
        for value in raw["segments"]
    )
    return RetrievalSegmentIndex(
        document_id=UUID(raw["document_id"]),
        derivation_version=raw["derivation_version"],
        configuration_fingerprint=raw["configuration_fingerprint"],
        segments=segments,
    )
