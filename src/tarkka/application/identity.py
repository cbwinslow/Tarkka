from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from tarkka.domain.discovery import DiscoveryRecord


@dataclass(frozen=True, slots=True)
class CanonicalWorkCandidate:
    canonical_key: str
    title: str
    year: int | None
    doi: str | None
    records: tuple[DiscoveryRecord, ...]
    external_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_ids", MappingProxyType(dict(self.external_ids)))


class CanonicalIdentityResolver:
    """Group only identities supported by strong external identifiers."""

    def resolve(self, records: Iterable[DiscoveryRecord]) -> tuple[CanonicalWorkCandidate, ...]:
        groups: dict[str, list[DiscoveryRecord]] = {}
        order: list[str] = []
        for record in records:
            key = _canonical_key(record)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(record)
        return tuple(_candidate(key, tuple(groups[key])) for key in order)


def _canonical_key(record: DiscoveryRecord) -> str:
    if record.doi:
        return f"doi:{_normalize_doi(record.doi)}"
    return f"provider:{record.provider}:{record.provider_id}"


def _normalize_doi(value: str) -> str:
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            return doi.removeprefix(prefix)
    return doi


def _candidate(key: str, records: tuple[DiscoveryRecord, ...]) -> CanonicalWorkCandidate:
    preferred = _preferred(records)
    external_ids: dict[str, str] = {}
    for record in records:
        external_ids.update(record.external_ids)
        external_ids[record.provider] = record.provider_id
    doi = _normalize_doi(preferred.doi) if preferred.doi else None
    return CanonicalWorkCandidate(
        canonical_key=key,
        title=preferred.title,
        year=preferred.year,
        doi=doi,
        records=records,
        external_ids=external_ids,
    )


def _preferred(records: tuple[DiscoveryRecord, ...]) -> DiscoveryRecord:
    # Prefer records with more useful compact metadata; ties retain source order.
    return max(
        records,
        key=lambda record: (
            int(record.abstract is not None),
            int(record.open_access_url is not None),
            int(record.cited_by_count is not None),
            int(record.year is not None),
        ),
    )
