from __future__ import annotations

from dataclasses import dataclass

from tarkka.application.discover import DiscoveryService
from tarkka.domain.discovery import DiscoveryPage, ResearchIntent, ResearchQuery


@dataclass
class _Provider:
    name: str

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        return DiscoveryPage(provider=self.name, records=())


def _service(*names: str) -> DiscoveryService:
    return DiscoveryService(tuple(_Provider(name) for name in names))


def test_broad_auto_prefers_openalex() -> None:
    result = _service("crossref", "openalex", "arxiv").discover(ResearchQuery("query"))
    assert result.providers_used == ("openalex",)


def test_preprint_intent_prefers_arxiv() -> None:
    result = _service("openalex", "arxiv").discover(
        ResearchQuery("query", intent=ResearchIntent.PREPRINT)
    )
    assert result.providers_used == ("arxiv",)


def test_citation_intent_prefers_semantic_scholar() -> None:
    result = _service("openalex", "semantic-scholar").discover(
        ResearchQuery("query", intent=ResearchIntent.CITATIONS)
    )
    assert result.providers_used == ("semantic-scholar",)


def test_bibliographic_intent_prefers_crossref() -> None:
    result = _service("openalex", "crossref").discover(
        ResearchQuery("query", intent=ResearchIntent.BIBLIOGRAPHIC)
    )
    assert result.providers_used == ("crossref",)


def test_intent_uses_deterministic_fallback() -> None:
    result = _service("openalex").discover(
        ResearchQuery("query", intent=ResearchIntent.PREPRINT)
    )
    assert result.providers_used == ("openalex",)


def test_explicit_provider_still_overrides_intent() -> None:
    from tarkka.domain.discovery import ProviderMode

    result = _service("openalex", "crossref").discover(
        ResearchQuery(
            "query",
            mode=ProviderMode.ONLY,
            providers=("crossref",),
            intent=ResearchIntent.PREPRINT,
        )
    )
    assert result.providers_used == ("crossref",)
