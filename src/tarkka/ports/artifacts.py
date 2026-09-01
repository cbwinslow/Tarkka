from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Protocol

from tarkka.domain.models import Artifact


class ArtifactStore(Protocol):
    """Immutable content-addressed artifact persistence.

    Tarkka treats byte identity as artifact identity across storage adapters. ``put_file`` and
    ``put_bytes`` must therefore derive the same SHA-256 digest, deterministic artifact UUID,
    and storage key for identical bytes regardless of source filename or acquisition path. The
    canonical artifact UUID is UUIDv5 in ``NAMESPACE_URL`` over ``urn:sha256:<digest>``.

    For local file ingestion, ``source_uri`` preserves the resolved source file URI. Missing
    source paths must raise ``FileNotFoundError`` rather than silently creating an empty artifact.
    Alternate storage adapters may map the storage key to a different backend while preserving
    the same domain artifact identity and exact stored bytes.
    """

    def put_file(self, source: Path) -> Artifact: ...

    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact: ...

    def path_for(self, artifact: Artifact) -> Path: ...

    def read_bytes(self, artifact: Artifact) -> bytes: ...

    def read_bytes_by_sha256(self, sha256: str) -> bytes: ...

    def exists(self, sha256: str) -> bool: ...


class StreamingArtifactStore(ArtifactStore, Protocol):
    """Optional ArtifactStore capability for bounded sequential reads.

    Implementations may stream from local files, object storage, or another durable backend.
    Callers own neither the returned reader nor its backend resources beyond the context manager.
    """

    def open_reader(self, artifact: Artifact) -> AbstractContextManager[BinaryIO]: ...
