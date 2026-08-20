from __future__ import annotations

from typing import Protocol

from tarkka.domain.discovery import SearchSnapshot


class SearchSnapshotRecorder(Protocol):
    def record(self, snapshot: SearchSnapshot) -> None: ...
