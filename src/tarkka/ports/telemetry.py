"""Boundary for opt-in agent usage telemetry."""

from __future__ import annotations

from typing import Protocol

from tarkka.domain.telemetry import AgentUsageEvent, AgentUsageExport


class AgentUsageRecorder(Protocol):
    """Record aggregate interface measurements without affecting user operations."""

    def record(self, event: AgentUsageEvent) -> None: ...


class AgentUsageExporter(Protocol):
    """Optionally export aggregate usage measurements to an external backend."""

    def export(self, event: AgentUsageExport) -> None: ...


def export_agent_usage(exporter: AgentUsageExporter, event: AgentUsageEvent) -> bool:
    """Export one aggregate measurement without changing caller outcome on failure."""
    try:
        exporter.export(AgentUsageExport.from_event(event))
    except Exception:
        return False
    return True
