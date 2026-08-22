from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.traversal import TraversalCheckpoint


class TraversalCheckpointRepository(Protocol):
    """Persistence boundary for evolving single-writer traversal state."""

    def save(self, checkpoint: TraversalCheckpoint) -> None: ...

    def get(self, checkpoint_id: UUID) -> TraversalCheckpoint | None: ...
