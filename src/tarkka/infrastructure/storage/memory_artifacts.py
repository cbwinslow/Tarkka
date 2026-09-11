"""In-memory ArtifactStore shim proving a port swap does not change hashes."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from tarkka.domain.identifiers import require_sha256
from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore


class MemoryArtifactStore:
    """Object-map artifact store with a local materialization cache for path_for."""

    def __init__(self, cache_root: Path) -> None:
        self._objects: dict[str, bytes] = {}
        self._cache = LocalArtifactStore(cache_root)

    def put_file(self, source: Path) -> Artifact:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        return self.put_bytes(
            source.read_bytes(),
            original_name=source.name,
            source_uri=source.as_uri(),
        )

    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        artifact = self._cache.put_bytes(
            data,
            original_name=original_name,
            source_uri=source_uri,
            media_type=media_type,
        )
        self._objects[artifact.sha256] = data
        return artifact

    def path_for(self, artifact: Artifact) -> Path:
        return self._cache.path_for(artifact)

    def read_bytes(self, artifact: Artifact) -> bytes:
        return self.read_bytes_by_sha256(artifact.sha256)

    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        require_sha256(sha256, field_name="artifact SHA-256")
        data = self._objects.get(sha256)
        if data is None:
            data = self._cache.read_bytes_by_sha256(sha256)
            self._objects[sha256] = data
        if hashlib.sha256(data).hexdigest() != sha256:
            raise OSError("artifact content does not match its SHA-256 storage key")
        return data

    def exists(self, sha256: str) -> bool:
        return sha256 in self._objects or self._cache.exists(sha256)

    @contextmanager
    def open_reader(self, artifact: Artifact) -> Iterator[BinaryIO]:
        with self._cache.open_reader(artifact) as handle:
            yield handle

    @staticmethod
    def storage_key_for_digest(sha256: str) -> PurePosixPath:
        return LocalArtifactStore.storage_key_for_digest(sha256)
