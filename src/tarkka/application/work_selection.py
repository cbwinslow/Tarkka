from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.application.identity import CanonicalIdentityResolver
from tarkka.application.works import WorkCatalogService, WorkIdentityConflictError
from tarkka.domain.models import Work
from tarkka.ports.snapshots import SearchSnapshotReader


class SnapshotSelectionError(RuntimeError):
    """Base error for explicit SearchSnapshot result selection failures."""


class SnapshotNotFoundError(SnapshotSelectionError):
    pass


class SnapshotRecordNotFoundError(SnapshotSelectionError):
    pass


class SnapshotRecordConflictError(SnapshotSelectionError):
    """Raised when a selected result conflicts with existing canonical Work identity."""


@dataclass(frozen=True, slots=True)
class SavedWorkSelection:
    snapshot_id: UUID
    result_index: int
    work: Work


class WorkSelectionService:
    """Persist one explicitly selected discovery result as a canonical Work."""

    def __init__(
        self,
        snapshots: SearchSnapshotReader,
        catalog: WorkCatalogService,
        resolver: CanonicalIdentityResolver | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._catalog = catalog
        self._resolver = resolver or CanonicalIdentityResolver()

    def save_snapshot_result(self, snapshot_id: UUID, result_index: int) -> SavedWorkSelection:
        if result_index < 0:
            raise SnapshotRecordNotFoundError("result index must be non-negative")
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise SnapshotNotFoundError(f"search snapshot not found: {snapshot_id}")
        if result_index >= len(snapshot.records):
            raise SnapshotRecordNotFoundError(
                f"result index {result_index} is out of range for snapshot {snapshot_id}"
            )

        record = snapshot.records[result_index]
        candidate = self._resolver.resolve((record,))[0]
        try:
            work = self._catalog.persist_candidate(candidate)
        except WorkIdentityConflictError as exc:
            raise SnapshotRecordConflictError(
                f"selected result {result_index} from snapshot {snapshot_id} conflicts with "
                f"existing canonical Work identity: {exc}"
            ) from exc
        return SavedWorkSelection(snapshot_id=snapshot_id, result_index=result_index, work=work)
