from __future__ import annotations

from pathlib import Path
from typing import Protocol

from tarkka.domain.models import Artifact, Document


class DocumentParser(Protocol):
    name: str
    version: str

    def supports(self, artifact: Artifact) -> bool: ...

    def parse(self, artifact: Artifact, path: Path) -> Document: ...
