from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from tarkka.application.identity import CanonicalWorkCandidate
from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.identifiers import try_normalize_arxiv_id, try_normalize_doi
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.ports.works import WorkMetadataEnricher, WorkRepository


class WorkIdentityConflictError(RuntimeError):
    """Raised when strong identifiers already point at different canonical Works."""


class WorkNotFoundError(LookupError):
    pass


class WorkEnrichmentError(RuntimeError):
    pass


class WorkCatalogService:
    """Persist canonical Work identity while preserving provider observations."""

    def __init__(self, repository: WorkRepository) -> None:
        self._repository = repository

    def persist_candidate(self, candidate: CanonicalWorkCandidate) -> Work:
        return self.persist_candidates((candidate,))[0]

    def persist_candidates(
        self,
        candidates: Iterable[CanonicalWorkCandidate],
    ) -> tuple[Work, ...]:
        """Persist a candidate batch atomically when the repository supports transactions."""
        candidate_tuple = tuple(candidates)
        if not candidate_tuple:
            return ()
        with self._repository.transaction():
            return tuple(self._persist_candidate(candidate) for candidate in candidate_tuple)

    def _persist_candidate(self, candidate: CanonicalWorkCandidate) -> Work:
        aliases = _candidate_aliases(candidate)
        matched: dict[UUID, Work] = {}
        for scheme, value in aliases:
            existing_match = self._repository.find_work_by_identifier(scheme, value)
            if existing_match is not None:
                matched[existing_match.work_id] = existing_match
        if len(matched) > 1:
            raise WorkIdentityConflictError(
                "candidate identifiers resolve to multiple canonical Works: "
                + ", ".join(str(work_id) for work_id in sorted(matched, key=str))
            )

        existing = next(iter(matched.values()), None)
        if existing is None:
            work = Work(
                work_id=uuid4(),
                title=candidate.title,
                publication_type=_first_metadata_str(candidate.records, "publication_type")
                or "unknown",
                publication_year=candidate.year,
                abstract=_first_abstract(candidate.records),
                venue=_first_metadata_str(candidate.records, "venue"),
            )
        else:
            work = _fill_missing_work_metadata(existing, candidate.records, candidate.year)

        self._repository.save_work(work)
        self._save_aliases(work.work_id, aliases)
        self._save_records(work.work_id, candidate.records)
        return work

    def enrich_by_doi(self, work_id: UUID, enricher: WorkMetadataEnricher) -> Work:
        record: DiscoveryRecord
        doi: str
        with self._repository.transaction():
            work = self._repository.get_work(work_id)
            if work is None:
                raise WorkNotFoundError(f"work not found: {work_id}")

            doi_value = next(
                (
                    identifier.value
                    for identifier in self._repository.list_identifiers(work_id)
                    if identifier.scheme == "doi"
                ),
                None,
            )
            if doi_value is None:
                raise WorkEnrichmentError("work has no DOI alias")
            doi = doi_value

        record = enricher.lookup_by_doi(doi)
        returned_doi = try_normalize_doi(record.doi)
        if returned_doi != doi:
            raise WorkEnrichmentError(
                f"{enricher.name} returned DOI {returned_doi!r} for requested DOI {doi!r}"
            )

        with self._repository.transaction():
            current = self._repository.get_work(work_id)
            if current is None:
                raise WorkNotFoundError(f"work not found during enrichment: {work_id}")
            self._save_records(work_id, (record,))
            self._save_aliases(work_id, _record_aliases(record))
            updated = _fill_missing_from_record(current, record)
            self._repository.save_work(updated)
            return updated

    def _save_aliases(self, work_id: UUID, aliases: Iterable[tuple[str, str]]) -> None:
        for scheme, value in aliases:
            existing = self._repository.find_work_by_identifier(scheme, value)
            if existing is not None and existing.work_id != work_id:
                raise WorkIdentityConflictError(
                    f"identifier {scheme}:{value} already belongs to work {existing.work_id}"
                )
            identifier_id = uuid5(NAMESPACE_URL, f"tarkka:work-id:{work_id}:{scheme}:{value}")
            self._repository.save_identifier(
                WorkIdentifier(
                    identifier_id=identifier_id,
                    work_id=work_id,
                    scheme=scheme,
                    value=value,
                )
            )

    def _save_records(self, work_id: UUID, records: Iterable[DiscoveryRecord]) -> None:
        for record in records:
            source_record_id = uuid5(
                NAMESPACE_URL,
                f"tarkka:source-record:{work_id}:{record.provider}:{record.provider_id}",
            )
            self._repository.save_source_record(
                WorkSourceRecord(
                    source_record_id=source_record_id,
                    work_id=work_id,
                    record=record,
                )
            )


def _candidate_aliases(candidate: CanonicalWorkCandidate) -> tuple[tuple[str, str], ...]:
    aliases: list[tuple[str, str]] = []
    if candidate.doi:
        doi = try_normalize_doi(candidate.doi)
        if doi:
            aliases.append(("doi", doi))
    for record in candidate.records:
        aliases.extend(_record_aliases(record))
    return _dedupe_aliases(aliases)


def _record_aliases(record: DiscoveryRecord) -> tuple[tuple[str, str], ...]:
    aliases: list[tuple[str, str]] = []
    provider_scheme = record.provider.strip().lower()
    provider_value = _normalized_alias_value(provider_scheme, record.provider_id)
    if provider_value:
        aliases.append((provider_scheme, provider_value))
    for raw_scheme, raw_value in record.external_ids.items():
        scheme = raw_scheme.strip().lower()
        if not scheme:
            continue
        value = _normalized_alias_value(scheme, raw_value)
        if value:
            aliases.append((scheme, value))
    return _dedupe_aliases(aliases)


def _normalized_alias_value(scheme: str, value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    if scheme == "doi":
        return try_normalize_doi(stripped)
    if scheme == "arxiv":
        return try_normalize_arxiv_id(stripped)
    return stripped


def _dedupe_aliases(aliases: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    seen: set[tuple[str, str]] = set()
    output: list[tuple[str, str]] = []
    for scheme, value in aliases:
        key = (scheme, value)
        if key not in seen:
            seen.add(key)
            output.append(key)
    return tuple(output)


def _first_abstract(records: Iterable[DiscoveryRecord]) -> str | None:
    return next((record.abstract for record in records if record.abstract), None)


def _first_metadata_str(records: Iterable[DiscoveryRecord], key: str) -> str | None:
    for record in records:
        value = record.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _fill_missing_work_metadata(
    work: Work,
    records: Iterable[DiscoveryRecord],
    candidate_year: int | None,
) -> Work:
    record_tuple = tuple(records)
    return replace(
        work,
        publication_type=(
            _first_metadata_str(record_tuple, "publication_type")
            if work.publication_type == "unknown"
            else work.publication_type
        )
        or "unknown",
        publication_year=work.publication_year or candidate_year,
        abstract=work.abstract or _first_abstract(record_tuple),
        venue=work.venue or _first_metadata_str(record_tuple, "venue"),
    )


def _fill_missing_from_record(work: Work, record: DiscoveryRecord) -> Work:
    publication_type = record.metadata.get("publication_type")
    venue = record.metadata.get("venue")
    return replace(
        work,
        publication_type=(
            publication_type
            if work.publication_type == "unknown" and isinstance(publication_type, str)
            else work.publication_type
        ),
        publication_year=work.publication_year or record.year,
        abstract=work.abstract or record.abstract,
        venue=work.venue or (venue if isinstance(venue, str) else None),
    )
