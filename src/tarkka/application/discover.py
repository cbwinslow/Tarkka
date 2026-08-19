from __future__ import annotations

from collections.abc import Iterable

from tarkka.domain.discovery import (
    DiscoveryRecord,
    DiscoveryResult,
    ProviderMode,
    ResearchQuery,
)
from tarkka.ports.discovery import DiscoveryProvider


class UnknownProviderError(ValueError):
    pass


class DiscoveryService:
    """Provider-neutral discovery with explicit selection and deterministic deduplication."""

    def __init__(self, providers: Iterable[DiscoveryProvider]) -> None:
        self._providers = {provider.name: provider for provider in providers}
        if not self._providers:
            raise ValueError("at least one discovery provider is required")

    def _select(self, query: ResearchQuery) -> tuple[DiscoveryProvider, ...]:
        if query.mode is ProviderMode.ALL:
            return tuple(self._providers[name] for name in sorted(self._providers))

        if query.mode is ProviderMode.ONLY:
            missing = [name for name in query.providers if name not in self._providers]
            if missing:
                raise UnknownProviderError(f"unknown discovery provider(s): {', '.join(missing)}")
            return tuple(self._providers[name] for name in query.providers)

        # AUTO deliberately starts narrow. OpenAlex is the preferred broad-discovery source;
        # callers can request `all` or `only` when exhaustive or source-specific behavior matters.
        if "openalex" in self._providers:
            return (self._providers["openalex"],)
        return (self._providers[sorted(self._providers)[0]],)

    def discover(self, query: ResearchQuery) -> DiscoveryResult:
        selected = self._select(query)
        pages = tuple(provider.search(query) for provider in selected)
        records = _deduplicate(record for page in pages for record in page.records)
        cursors = {
            page.provider: page.next_cursor
            for page in pages
            if page.next_cursor is not None
        }
        return DiscoveryResult(
            query=query,
            providers_used=tuple(provider.name for provider in selected),
            records=records[: query.limit],
            next_cursors=cursors,
        )


def _deduplicate(records: Iterable[DiscoveryRecord]) -> tuple[DiscoveryRecord, ...]:
    seen: set[tuple[str, str]] = set()
    output: list[DiscoveryRecord] = []
    for record in records:
        if record.doi:
            key = ("doi", _normalize_doi(record.doi))
        else:
            key = ("provider", f"{record.provider}:{record.provider_id}")
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return tuple(output)


def _normalize_doi(value: str) -> str:
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            return doi.removeprefix(prefix)
    return doi
