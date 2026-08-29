from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest

from tarkka.application.discover import (
    DefaultProviderSelector,
    DiscoveryProviderError,
    DiscoveryService,
    UnknownProviderError,
)
from tarkka.domain.discovery import (
    DiscoveryPage,
    DiscoveryRecord,
    ProviderMode,
    ResearchIntent,
    ResearchQuery,
    SearchSnapshot,
)
from tarkka.ports.discovery import DiscoveryProvider, ProviderSelector
from tarkka.ports.snapshots import SearchSnapshotRecorder

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _record(
    provider: str,
    provider_id: str,
    *,
    doi: str | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title=f"record {provider}:{provider_id}",
        doi=doi,
    )


@dataclass
class _Provider:
    name: str
    returned_provider: str | None = None
    record_count: int = 1
    next_cursor: str | None = None
    error: OSError | ValueError | None = None
    seen_queries: list[ResearchQuery] = field(default_factory=list)

    def search(self, query: ResearchQuery) -> DiscoveryPage:
        self.seen_queries.append(query)
        if self.error is not None:
            raise self.error
        provider = self.returned_provider or self.name
        records = tuple(
            _record(provider, f"{self.name}-{index}") for index in range(self.record_count)
        )
        return DiscoveryPage(
            provider=provider,
            records=records,
            next_cursor=self.next_cursor,
        )


@dataclass
class _Recorder:
    snapshots: list[SearchSnapshot] = field(default_factory=list)

    def record(self, snapshot: SearchSnapshot) -> None:
        self.snapshots.append(snapshot)


@dataclass
class _Selector:
    selected: tuple[DiscoveryProvider, ...]

    def select(
        self,
        query: ResearchQuery,
        providers: dict[str, DiscoveryProvider],
    ) -> tuple[DiscoveryProvider, ...]:
        del query, providers
        return self.selected


def _provider(name: str, **kwargs: object) -> _Provider:
    return _Provider(name=name, **kwargs)  # type: ignore[arg-type]


def test_default_selector_rejects_empty_and_covers_all_policy_fallbacks() -> None:
    selector = DefaultProviderSelector()
    with pytest.raises(ValueError, match="at least one provider"):
        selector.select(ResearchQuery(text="x"), {})

    providers = {
        name: cast(DiscoveryProvider, _provider(name))
        for name in ("arxiv", "crossref", "openalex", "semantic-scholar")
    }
    cases = (
        (ResearchQuery(text="x", intent=ResearchIntent.PREPRINT), "arxiv"),
        (ResearchQuery(text="x", intent=ResearchIntent.CITATIONS), "semantic-scholar"),
        (ResearchQuery(text="x", intent=ResearchIntent.BIBLIOGRAPHIC), "crossref"),
        (ResearchQuery(text="x", require_open_access=True), "openalex"),
        (ResearchQuery(text="x"), "openalex"),
    )
    for query, expected in cases:
        assert selector.select(query, providers)[0].name == expected

    fallback = {"zeta": cast(DiscoveryProvider, _provider("zeta"))}
    assert selector.select(ResearchQuery(text="x"), fallback)[0].name == "zeta"


def test_discovery_service_rejects_empty_duplicate_and_unknown_explicit_providers() -> None:
    with pytest.raises(ValueError, match="at least one discovery provider"):
        DiscoveryService(())

    with pytest.raises(ValueError, match="duplicate discovery provider"):
        DiscoveryService(
            (
                cast(DiscoveryProvider, _provider("dup")),
                cast(DiscoveryProvider, _provider("dup")),
            )
        )

    service = DiscoveryService((cast(DiscoveryProvider, _provider("known")),))
    query = ResearchQuery(text="x", mode=ProviderMode.ONLY, providers=("missing",))
    with pytest.raises(UnknownProviderError, match="missing"):
        service.discover(query)


def test_auto_selector_rejects_empty_unknown_and_duplicate_results() -> None:
    known = cast(DiscoveryProvider, _provider("known"))
    unknown = cast(DiscoveryProvider, _provider("unknown"))

    for selected, message in (
        ((), "returned no providers"),
        ((unknown,), "unknown provider"),
        ((known, known), "duplicate provider"),
    ):
        service = DiscoveryService(
            (known,),
            selector=cast(ProviderSelector, _Selector(selected)),
        )
        with pytest.raises(ValueError, match=message):
            service.discover(ResearchQuery(text="x"))


def test_discover_records_snapshot_cursor_and_deduplicates_canonical_doi() -> None:
    recorder = _Recorder()

    @dataclass
    class _DoiProvider:
        name: str
        record: DiscoveryRecord
        next_cursor: str | None = None

        def search(self, query: ResearchQuery) -> DiscoveryPage:
            return DiscoveryPage(
                provider=self.name,
                records=(self.record,),
                next_cursor=self.next_cursor,
            )

    left = _DoiProvider("a", _record("a", "1", doi="doi:10.1000/SAME"), "next-a")
    right = _DoiProvider(
        "b",
        _record("b", "2", doi="https://doi.org/10.1000/same"),
        None,
    )
    service = DiscoveryService(
        (cast(DiscoveryProvider, left), cast(DiscoveryProvider, right)),
        snapshot_recorder=cast(SearchSnapshotRecorder, recorder),
    )
    result = service.discover(ResearchQuery(text="x", mode=ProviderMode.ALL, limit=2))

    assert result.providers_used == ("a", "b")
    assert [record.provider_id for record in result.records] == ["1"]
    assert dict(result.next_cursors) == {"a": "next-a"}
    assert len(recorder.snapshots) == 1
    assert recorder.snapshots[0].snapshot_id == result.snapshot_id


def test_provider_budgeting_validates_cursors_and_distributes_remainder() -> None:
    a = _provider("a")
    b = _provider("b")
    service = DiscoveryService(
        (cast(DiscoveryProvider, a), cast(DiscoveryProvider, b))
    )

    with pytest.raises(ValueError, match="unselected provider"):
        service.discover(
            ResearchQuery(
                text="x",
                mode=ProviderMode.ONLY,
                providers=("a",),
                cursors={"b": "cursor"},
            )
        )

    with pytest.raises(ValueError, match="single cursor is ambiguous"):
        service.discover(
            ResearchQuery(text="x", mode=ProviderMode.ALL, limit=2, cursor="legacy")
        )

    with pytest.raises(ValueError, match="smaller than selected provider count"):
        service.discover(ResearchQuery(text="x", mode=ProviderMode.ALL, limit=1))

    result = service.discover(
        ResearchQuery(
            text="x",
            mode=ProviderMode.ALL,
            limit=5,
            cursors={"a": "cursor-a", "b": "cursor-b"},
        )
    )
    assert len(result.records) == 2
    assert a.seen_queries[-1].limit == 3
    assert b.seen_queries[-1].limit == 2
    assert a.seen_queries[-1].cursor == "cursor-a"
    assert b.seen_queries[-1].cursor == "cursor-b"
    assert dict(a.seen_queries[-1].cursors) == {}


def test_single_provider_inherits_legacy_cursor() -> None:
    provider = _provider("solo")
    service = DiscoveryService((cast(DiscoveryProvider, provider),))
    service.discover(ResearchQuery(text="x", limit=2, cursor="legacy-cursor"))
    assert provider.seen_queries[-1].cursor == "legacy-cursor"


def test_provider_contract_rejects_mismatched_page_and_oversized_page() -> None:
    wrong = _provider("expected", returned_provider="other")
    service = DiscoveryService((cast(DiscoveryProvider, wrong),))
    with pytest.raises(ValueError, match="returned page for"):
        service.discover(ResearchQuery(text="x"))

    oversized = _provider("large", record_count=2)
    service = DiscoveryService((cast(DiscoveryProvider, oversized),))
    with pytest.raises(ValueError, match="returned 2 records for limit 1"):
        service.discover(ResearchQuery(text="x", limit=1))


def test_multi_provider_failures_are_aggregated_deterministically() -> None:
    broken_b = _provider("b", error=OSError("offline"))
    broken_a = _provider("a", error=ValueError("bad payload"))
    service = DiscoveryService(
        (cast(DiscoveryProvider, broken_b), cast(DiscoveryProvider, broken_a))
    )

    with pytest.raises(DiscoveryProviderError) as captured:
        service.discover(ResearchQuery(text="x", mode=ProviderMode.ALL, limit=2))

    assert "a: bad payload; b: offline" in str(captured.value)
    assert isinstance(captured.value.__cause__, ExceptionGroup)
    assert len(captured.value.__cause__.exceptions) == 2


def test_provider_identity_dedup_keeps_distinct_provider_records_without_valid_doi() -> None:
    @dataclass
    class _RecordsProvider:
        name: str
        records: tuple[DiscoveryRecord, ...]

        def search(self, query: ResearchQuery) -> DiscoveryPage:
            return DiscoveryPage(provider=self.name, records=self.records[: query.limit])

    records = (
        _record("a", "same", doi="not-a-doi"),
        _record("a", "same", doi=None),
        _record("a", "other", doi=None),
    )
    provider = _RecordsProvider("a", records)
    result = DiscoveryService((cast(DiscoveryProvider, provider),)).discover(
        ResearchQuery(text="x", limit=3)
    )
    assert [record.provider_id for record in result.records] == ["same", "other"]
