from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4


class ProviderMode(StrEnum):
    """How a discovery request chooses providers."""

    AUTO = "auto"
    ONLY = "only"
    ALL = "all"


class ResearchIntent(StrEnum):
    """Provider-neutral intent used by AUTO discovery policy."""

    BROAD = "broad"
    PREPRINT = "preprint"
    CITATIONS = "citations"
    BIBLIOGRAPHIC = "bibliographic"


@dataclass(frozen=True, slots=True)
class ResearchQuery:
    text: str
    limit: int = 25
    cursor: str | None = None
    cursors: Mapping[str, str] = field(default_factory=dict)
    mode: ProviderMode = ProviderMode.AUTO
    providers: tuple[str, ...] = ()
    intent: ResearchIntent = ResearchIntent.BROAD
    require_open_access: bool = False
    year_from: int | None = None
    year_to: int | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("research query must not be blank")
        if not 1 <= self.limit <= 1000:
            raise ValueError("query limit must be between 1 and 1000")
        if self.mode is ProviderMode.ONLY and not self.providers:
            raise ValueError("mode=only requires at least one provider")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must be <= year_to")
        if self.cursor and self.cursors:
            raise ValueError("use either cursor or provider-keyed cursors, not both")
        object.__setattr__(self, "cursors", MappingProxyType(dict(self.cursors)))


@dataclass(frozen=True, slots=True)
class DiscoveryRecord:
    provider: str
    provider_id: str
    title: str
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    landing_page_url: str | None = None
    open_access_url: str | None = None
    cited_by_count: int | None = None
    external_ids: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.provider_id.strip():
            raise ValueError("provider and provider_id must not be blank")
        if not self.title.strip():
            raise ValueError("discovery title must not be blank")
        object.__setattr__(self, "external_ids", MappingProxyType(dict(self.external_ids)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    provider: str
    records: tuple[DiscoveryRecord, ...]
    next_cursor: str | None = None
    total: int | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    query: ResearchQuery
    providers_used: tuple[str, ...]
    records: tuple[DiscoveryRecord, ...]
    next_cursors: Mapping[str, str] = field(default_factory=dict)
    snapshot_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "next_cursors", MappingProxyType(dict(self.next_cursors)))


@dataclass(frozen=True, slots=True)
class SearchSnapshot:
    """Immutable record of what a provider selection returned at one point in time."""

    snapshot_id: UUID
    query: ResearchQuery
    providers_used: tuple[str, ...]
    records: tuple[DiscoveryRecord, ...]
    next_cursors: Mapping[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "next_cursors", MappingProxyType(dict(self.next_cursors)))

    @classmethod
    def from_result(cls, result: DiscoveryResult) -> SearchSnapshot:
        return cls(
            snapshot_id=result.snapshot_id,
            query=result.query,
            providers_used=result.providers_used,
            records=result.records,
            next_cursors=result.next_cursors,
        )
