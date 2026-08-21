from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from tarkka.domain.source_observations import Capability, CapabilityManifest


class CapabilityAwareAdapter(Protocol):
    """Minimal contract for adapters that expose a capability manifest."""

    @property
    def manifest(self) -> CapabilityManifest: ...


TCapabilityAdapter = TypeVar("TCapabilityAdapter", bound=CapabilityAwareAdapter)


def adapters_supporting(
    adapters: Iterable[TCapabilityAdapter],
    *capabilities: Capability,
) -> tuple[TCapabilityAdapter, ...]:
    """Select adapters by capability without branching on provider names.

    An empty capability requirement intentionally returns every adapter, making this
    function an identity filter when callers build capability requirements dynamically.
    """
    return tuple(
        adapter for adapter in adapters if adapter.manifest.supports(*capabilities)
    )
