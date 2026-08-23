from __future__ import annotations

from pathlib import Path
from typing import Protocol

from tarkka.domain.models import Artifact


class ArtifactStore(Protocol):
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

    def exists(self, sha256: str) -> bool: ...
