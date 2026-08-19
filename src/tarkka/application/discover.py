from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed

from tarkka.domain.discovery import (
    DiscoveryPage,
    DiscoveryRecord,
    DiscoveryResult,
    ProviderMode,
    ResearchQuery,
    SearchSnapshot,
)
from tarkka.domain.identifiers import normalize_doi
from tarkka.ports.discovery import DiscoveryProvider, ProviderSelector
from tarkka.ports.snapshots import SearchSnapshotRecorder


class UnknownProviderError(ValueError):
    pass


class DiscoveryProviderError(RuntimeError):
    pass


class DefaultProviderSelector:
    """Narrow default policy that can be replaced without changing DiscoveryService."""

    def select(
        self,
        query: ResearchQuery,
        providers: Mapping[str, DiscoveryProvider],
    ) -> tuple[DiscoveryProvider, ...]:
        del query
        if "openalex" in providers:
            return (providers["openalex"],)
        return (providers[sorted(providers)[0]],)


class DiscoveryService:
    """Provider-neutral discovery with explicit selection and deterministic deduplication."""

    def __init__(
        self,
        providers: Iterable[DiscoveryProvider],
        *,
        selector: ProviderSelector | None = None,
        snapshot_recorder: SearchSnapshotRecorder | None = None,
    ) -> None:
        self._providers = {provider.name: provider for provider in providers}
        if not self._providers:
            raise ValueError("at least one discovery provider is required")
        self._selector = selector or DefaultProviderSelector()
        self._snapshot_recorder = snapshot_recorder

    def _select(self, query: ResearchQuery) -> tuple[DiscoveryProvider, ...]:
        if query.mode is ProviderMode.ALL:
            return tuple(self._providers[name] for name in sorted(self._providers))
        if query.mode is ProviderMode.ONLY:
            missing = [name for name in query.providers if name not in self._providers]
            if missing:
                raise UnknownProviderError(f"unknown discovery provider(s): {', '.join(missing)}")
            return tuple(self._providers[name] for name in query.providers)
        return self._selector.select(query, self._providers)

    def discover(self, query: ResearchQuery) -> DiscoveryResult:
        selected = self._select(query)
        pages = _search_selected(selected, query)
        records = _deduplicate(record for page in pages for record in page.records)
        cursors = {
            page.provider: page.next_cursor
            for page in pages
            if page.next_cursor is not None
        }
        result = DiscoveryResult(
            query=query,
            providers_used=tuple(page.provider for page in pages),
            records=records[: query.limit],
            next_cursors=cursors,
        )
        if self._snapshot_recorder is not None:
            self._snapshot_recorder.record(SearchSnapshot.from_result(result))
        return result


def _search_selected(
    providers: tuple[DiscoveryProvider, ...],
    query: ResearchQuery,
) -> tuple[DiscoveryPage, ...]:
    if len(providers) == 1:
        return (providers[0].search(query),)

    pages: dict[str, DiscoveryPage] = {}
    errors: dict[str, BaseException] = {}
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {executor.submit(provider.search, query): provider.name for provider in providers}
        for future in as_completed(futures):
            name = futures[future]
            try:
                pages[name] = future.result()
            except Exception as exc:
                errors[name] = exc
    if errors:
        details = "; ".join(f"{name}: {error}" for name, error in sorted(errors.items()))
        raise DiscoveryProviderError(f"discovery provider failure(s): {details}")
    return tuple(pages[provider.name] for provider in providers)


def _deduplicate(records: Iterable[DiscoveryRecord]) -> tuple[DiscoveryRecord, ...]:
    seen: set[tuple[str, str]] = set()
    output: list[DiscoveryRecord] = []
    for record in records:
        key = (
            ("doi", normalize_doi(record.doi))
            if record.doi
            else ("provider", f"{record.provider}:{record.provider_id}")
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return tuple(output)
