"""A from-scratch ArtifactStore implementation for docs/CONFORMANCE.md's example.

This is intentionally not one of Tarkka's own reference adapters (see
``src/tarkka/infrastructure/storage/local_artifacts.py`` for that): it uses a flat,
unsharded object directory rather than a two-level sha256 prefix layout. It exists so
the adapter example in the conformance kit documentation is real, importable code that
CI exercises, rather than illustrative prose that can silently drift from the actual
``ArtifactStore`` protocol as it evolves.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from tarkka.domain.models import Artifact


class ExampleArtifactStore:
    """Minimal content-addressed store: one file per digest in a flat directory."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def put_file(self, source: Path) -> Artifact:
        data = source.read_bytes()
        return self._put(
            data,
            original_name=source.name,
            source_uri=source.resolve().as_uri(),
        )

    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        return self._put(
            data,
            original_name=original_name,
            source_uri=source_uri,
            media_type=media_type,
        )

    def path_for(self, artifact: Artifact) -> Path:
        return self._object_path(artifact.sha256)

    def read_bytes(self, artifact: Artifact) -> bytes:
        return self.read_bytes_by_sha256(artifact.sha256)

    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        return self._object_path(sha256).read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._object_path(sha256).exists()

    def _object_path(self, sha256: str) -> Path:
        return self._root / sha256

    def _put(
        self,
        data: bytes,
        *,
        original_name: str | None,
        source_uri: str | None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        sha256 = hashlib.sha256(data).hexdigest()
        path = self._object_path(sha256)
        if not path.exists():
            path.write_bytes(data)
        return Artifact(
            artifact_id=uuid5(NAMESPACE_URL, f"urn:sha256:{sha256}"),
            sha256=sha256,
            size_bytes=len(data),
            media_type=media_type,
            storage_key=PurePosixPath(sha256),
            original_name=original_name,
            source_uri=source_uri,
        )
