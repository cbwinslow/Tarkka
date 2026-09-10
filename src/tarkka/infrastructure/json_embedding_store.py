"""Atomic JSON reference storage for immutable retrieval embedding derivations."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.retrieval_embeddings import EmbeddingNormalization, SegmentEmbedding
from tarkka.infrastructure.storage.locking import exclusive_lock
from tarkka.ports.embedding_stores import EmbeddingStore


class JsonEmbeddingStore(EmbeddingStore):
    """Persist immutable embeddings in a separate atomic catalog."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "embeddings": {}})

    def put(self, embedding: SegmentEmbedding) -> None:
        with exclusive_lock(self.path):
            data = self._read()
            key = str(embedding.embedding_id)
            existing = data["embeddings"].get(key)
            if existing is not None and _from_dict(existing) != embedding:
                raise RuntimeError("embedding catalog identity collision")
            if existing is None:
                data["embeddings"][key] = _to_dict(embedding)
                self._write(data)

    def get(self, embedding_id: UUID) -> SegmentEmbedding | None:
        raw = self._read()["embeddings"].get(str(embedding_id))
        return _from_dict(raw) if raw is not None else None

    def list_for_segment(self, segment_id: UUID) -> tuple[SegmentEmbedding, ...]:
        return tuple(
            sorted(
                (
                    _from_dict(value)
                    for value in self._read()["embeddings"].values()
                    if value["segment_id"] == str(segment_id)
                ),
                key=lambda item: (
                    item.model_identifier,
                    item.model_revision,
                    item.configuration_fingerprint,
                    str(item.embedding_id),
                ),
            )
        )

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data.get("embeddings"), dict):
                raise ValueError("unsupported catalog")
            return cast(dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("unable to read embedding catalog") from exc

    def _write(self, data: dict[str, Any]) -> None:
        fd, name = tempfile.mkstemp(prefix=".tarkka-embeddings-", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def _to_dict(embedding: SegmentEmbedding) -> dict[str, object]:
    return {
        "embedding_id": str(embedding.embedding_id),
        "segment_id": str(embedding.segment_id),
        "segment_digest": embedding.segment_digest,
        "segment_derivation_version": embedding.segment_derivation_version,
        "segment_configuration_fingerprint": embedding.segment_configuration_fingerprint,
        "model_identifier": embedding.model_identifier,
        "model_revision": embedding.model_revision,
        "configuration_fingerprint": embedding.configuration_fingerprint,
        "normalization": embedding.normalization.value,
        "values": list(embedding.values),
        "dimension": embedding.dimension,
    }


def _from_dict(raw: dict[str, Any]) -> SegmentEmbedding:
    return SegmentEmbedding(
        embedding_id=UUID(raw["embedding_id"]),
        segment_id=UUID(raw["segment_id"]),
        segment_digest=raw["segment_digest"],
        segment_derivation_version=raw["segment_derivation_version"],
        segment_configuration_fingerprint=raw["segment_configuration_fingerprint"],
        model_identifier=raw["model_identifier"],
        model_revision=raw["model_revision"],
        configuration_fingerprint=raw["configuration_fingerprint"],
        normalization=EmbeddingNormalization(raw["normalization"]),
        values=tuple(raw["values"]),
        dimension=raw["dimension"],
    )
