"""Explicitly configured append-only local storage for agent usage telemetry."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonlAgentUsageRecorder:
    """Persist aggregate telemetry without request arguments or source text."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: AgentUsageEvent) -> None:
        payload = {
            "occurred_at": event.occurred_at.isoformat(),
            "interface": event.interface,
            "operation_id": event.operation_id,
            "outcome": event.outcome,
            "elapsed_ms": event.elapsed_ms,
            "response_bytes": event.response_bytes,
            "estimated_tokens": event.estimated_tokens,
            "error_code": event.error_code,
        }
        with exclusive_lock(self.path), self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
