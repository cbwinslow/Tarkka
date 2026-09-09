"""Explicitly configured append-only local storage for agent usage telemetry."""

from __future__ import annotations

import json
import os
from datetime import datetime
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


class JsonlAgentUsageReader:
    """Read aggregate telemetry events without returning raw ledger payloads."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def read(self) -> tuple[AgentUsageEvent, ...]:
        """Return validated events or a safe, line-numbered ledger failure."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RuntimeError("unable to read telemetry ledger") from exc
        events: list[AgentUsageEvent] = []
        for line_number, line in enumerate(lines, start=1):
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("event must be an object")
                events.append(
                    AgentUsageEvent(
                        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                        interface=payload["interface"],
                        operation_id=payload["operation_id"],
                        outcome=payload["outcome"],
                        elapsed_ms=payload["elapsed_ms"],
                        response_bytes=payload["response_bytes"],
                        estimated_tokens=payload["estimated_tokens"],
                        error_code=payload["error_code"],
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"invalid telemetry ledger line {line_number}") from exc
        return tuple(events)
