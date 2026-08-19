from __future__ import annotations

from dataclasses import dataclass

from tarkka.application.discover import DiscoveryService, UnknownProviderError
from tarkka.domain.discovery import (
    DiscoveryPage,
    DiscoveryRecord,
    ProviderMode,
    ResearchQuery,
)


@dataclass
class _Provider:
    name: str
    records: tuple[DiscoveryRecord, ...]

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        return DiscoveryPage(provider=self.name, records=self.records)


def _record(provider: str, provider_id: str, *, doi: str | None = None) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title=f"Paper {provider_id}",
        doi=doi,
    )


def test_auto_prefers_openalex() -> None:
    service = DiscoveryService(
        (
            _Provider("crossref", (_record("crossref", "1"),)),
            _Provider("openalex", (_record("openalex", "W1"),)),
        )
    )

    result = service.discover(ResearchQuery("baseball prediction"))

    assert result.providers_used == ("openalex",)
    assert [record.provider for record in result.records] == ["openalex"]


def test_all_fans_out_and_deduplicates_by_doi() -> None:
    service = DiscoveryService(
        (
            _Provider("openalex", (_record("openalex", "W1", doi="10.1/ABC"),)),
            _Provider("crossref", (_record("crossref", "10.1/abc", doi="https://doi.org/10.1/abc"),)),
        )
    )

    result = service.discover(
        ResearchQuery("baseball prediction", mode=ProviderMode.ALL, limit=10)
    )

    assert result.providers_used == ("crossref", "openalex")
    assert len(result.records) == 1


def test_only_rejects_unknown_provider() -> None:
    service = DiscoveryService((_Provider("openalex", ()),))

    try:
        service.discover(
            ResearchQuery("query", mode=ProviderMode.ONLY, providers=("missing",))
        )
    except UnknownProviderError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected UnknownProviderError")
