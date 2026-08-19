from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from tarkka.application.discover import DiscoveryService, UnknownProviderError
from tarkka.domain.discovery import (
    DiscoveryPage,
    DiscoveryRecord,
    ProviderMode,
    ResearchQuery,
)
from tarkka.ports.discovery import DiscoveryProvider


@dataclass
class _Provider:
    name: str
    records: tuple[DiscoveryRecord, ...]
    seen_queries: list[ResearchQuery] = field(default_factory=list)

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        self.seen_queries.append(query)
        return DiscoveryPage(
            provider=self.name,
            records=self.records,
            next_cursor=f"{self.name}-next",
        )


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
            _Provider("openalex", (_record("openalex", "W1", doi="10.1234/ABC"),)),
            _Provider(
                "crossref",
                (_record("crossref", "10.1234/abc", doi="https://doi.org/10.1234/abc"),),
            ),
        )
    )

    result = service.discover(
        ResearchQuery("baseball prediction", mode=ProviderMode.ALL, limit=10)
    )

    assert result.providers_used == ("crossref", "openalex")
    assert len(result.records) == 1


def test_only_rejects_unknown_provider() -> None:
    service = DiscoveryService((_Provider("openalex", ()),))

    with pytest.raises(UnknownProviderError, match="missing"):
        service.discover(
            ResearchQuery("query", mode=ProviderMode.ONLY, providers=("missing",))
        )


def test_duplicate_provider_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate discovery provider"):
        DiscoveryService((_Provider("openalex", ()), _Provider("openalex", ())))


def test_multi_provider_cursors_round_trip_to_their_own_provider() -> None:
    openalex = _Provider("openalex", (_record("openalex", "W1"),))
    crossref = _Provider("crossref", (_record("crossref", "C1"),))
    service = DiscoveryService((openalex, crossref))

    result = service.discover(
        ResearchQuery(
            "query",
            mode=ProviderMode.ONLY,
            providers=("openalex", "crossref"),
            limit=10,
            cursors={"openalex": "oa-cursor", "crossref": "cr-cursor"},
        )
    )

    assert openalex.seen_queries[0].cursor == "oa-cursor"
    assert crossref.seen_queries[0].cursor == "cr-cursor"
    assert openalex.seen_queries[0].limit == 5
    assert crossref.seen_queries[0].limit == 5
    assert result.next_cursors == {
        "openalex": "openalex-next",
        "crossref": "crossref-next",
    }


def test_multi_provider_limit_must_cover_each_provider() -> None:
    service = DiscoveryService((_Provider("openalex", ()), _Provider("crossref", ())))

    with pytest.raises(ValueError, match="smaller than selected provider count"):
        service.discover(ResearchQuery("query", mode=ProviderMode.ALL, limit=1))


def test_cursor_for_unselected_provider_is_rejected() -> None:
    service = DiscoveryService((_Provider("openalex", ()), _Provider("crossref", ())))

    with pytest.raises(ValueError, match="unselected provider"):
        service.discover(
            ResearchQuery(
                "query",
                mode=ProviderMode.ONLY,
                providers=("openalex",),
                cursors={"crossref": "cursor"},
            )
        )


def test_auto_selector_is_replaceable() -> None:
    class _Selector:
        def select(
            self,
            query: ResearchQuery,
            providers: Mapping[str, DiscoveryProvider],
        ) -> tuple[DiscoveryProvider, ...]:
            del query
            return (providers["crossref"],)

    service = DiscoveryService(
        (
            _Provider("openalex", (_record("openalex", "W1"),)),
            _Provider("crossref", (_record("crossref", "C1"),)),
        ),
        selector=_Selector(),
    )

    result = service.discover(ResearchQuery("query"))

    assert result.providers_used == ("crossref",)


def test_auto_selector_must_return_provider() -> None:
    class _EmptySelector:
        def select(
            self,
            query: ResearchQuery,
            providers: Mapping[str, DiscoveryProvider],
        ) -> tuple[DiscoveryProvider, ...]:
            del query, providers
            return ()

    service = DiscoveryService((_Provider("openalex", ()),), selector=_EmptySelector())

    with pytest.raises(ValueError, match="returned no providers"):
        service.discover(ResearchQuery("query"))
