from __future__ import annotations

import json
import os
from pathlib import Path

from tarkka.domain.models import Acquisition
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonlAcquisitionLog:
    """Append-only local provenance log for artifact acquisition events."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, acquisition: Acquisition) -> None:
        payload = {
            "acquisition_id": str(acquisition.acquisition_id),
            "artifact_id": str(acquisition.artifact_id),
            "source_uri": acquisition.source_uri,
            "acquired_at": acquisition.acquired_at.isoformat(),
            "original_name": acquisition.original_name,
            "metadata": dict(acquisition.metadata),
        }
        line = json.dumps(payload, sort_keys=True) + "\n"
        with exclusive_lock(self.path), self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
