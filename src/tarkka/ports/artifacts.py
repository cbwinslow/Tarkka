from __future__ import annotations

from pathlib import Path
from typing import Protocol

from tarkka.domain.models import Artifact


class ArtifactStore(Protocol):
    def put_file(self, source: Path) -> Artifact: ...

    def read_bytes(self, artifact: Artifact) -> bytes: ...

    def exists(self, sha256: str) -> bool: ...
