"""Boundary for opt-in agent usage telemetry."""

from __future__ import annotations

from typing import Protocol

from tarkka.domain.telemetry import AgentUsageEvent


class AgentUsageRecorder(Protocol):
    """Record aggregate interface measurements without affecting user operations."""

    def record(self, event: AgentUsageEvent) -> None: ...
