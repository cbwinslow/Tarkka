from __future__ import annotations

from typing import Protocol

from tarkka.domain.discovery import DiscoveryPage, ResearchQuery


class DiscoveryProvider(Protocol):
    name: str

    def search(self, query: ResearchQuery) -> DiscoveryPage: ...
