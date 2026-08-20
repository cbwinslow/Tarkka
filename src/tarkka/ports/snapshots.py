from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.discovery import SearchSnapshot


class SearchSnapshotRecorder(Protocol):
    def record(self, snapshot: SearchSnapshot) -> None: ...


class SearchSnapshotReader(Protocol):
    def get(self, snapshot_id: UUID) -> SearchSnapshot | None: ...
