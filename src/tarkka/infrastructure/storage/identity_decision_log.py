from __future__ import annotations

import json
import os
from pathlib import Path

from tarkka.domain.identity_candidates import IdentityDecisionRecord
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonlIdentityDecisionLog:
    """Append-only local audit log for explicit fuzzy-identity review decisions."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, decision: IdentityDecisionRecord) -> None:
        payload = {
            "candidate_id": str(decision.candidate_id),
            "decision": decision.decision.value,
            "snapshot_id": str(decision.snapshot_id),
            "left_index": decision.left_index,
            "right_index": decision.right_index,
            "actor": decision.actor,
            "rationale": decision.rationale,
            "decided_at": decision.decided_at.isoformat(),
        }
        line = json.dumps(payload, sort_keys=True) + "\n"
        with exclusive_lock(self.path), self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
