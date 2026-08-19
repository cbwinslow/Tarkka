from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from tarkka.domain.discovery import DiscoveryPage, ResearchQuery


class DiscoveryProvider(Protocol):
    name: str

    def search(self, query: ResearchQuery) -> DiscoveryPage: ...


class ProviderSelector(Protocol):
    """Choose providers for AUTO discovery policy."""

    def select(
        self,
        query: ResearchQuery,
        providers: Mapping[str, DiscoveryProvider],
    ) -> tuple[DiscoveryProvider, ...]: ...
