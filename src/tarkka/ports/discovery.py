from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from tarkka.domain.discovery import DiscoveryPage, ResearchQuery


class DiscoveryProvider(Protocol):
    name: str

    def search(self, query: ResearchQuery) -> DiscoveryPage: ...


class ProviderSelector(Protocol):
    """Choose providers for AUTO discovery policy.

    ``providers`` must be non-empty; selectors should raise ``ValueError`` if that contract is
    violated. Implementations should be deterministic for the same query and provider set. They may
    return one or multiple providers and can consider query intent, credentials, rate limits,
    provider health, cost/latency budgets, or domain-specific coverage.
    """

    def select(
        self,
        query: ResearchQuery,
        providers: Mapping[str, DiscoveryProvider],
    ) -> tuple[DiscoveryProvider, ...]: ...
