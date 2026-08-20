from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.application.identity import CanonicalIdentityResolver
from tarkka.application.works import WorkCatalogService, WorkEnrichmentError
from tarkka.domain.discovery import DiscoveryRecord
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository


def _record(
    provider: str,
    provider_id: str,
    *,
    doi: str | None = None,
    title: str = "Shared paper",
    year: int | None = 2024,
    abstract: str | None = None,
    external_ids: dict[str, str] | None = None,
    metadata: dict[str, str] | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title=title,
        year=year,
        doi=doi,
        abstract=abstract,
        external_ids=external_ids or {},
        metadata=metadata or {},
    )


class _Enricher:
    name = "crossref"

    def __init__(self, record: DiscoveryRecord) -> None:
        self.record = record
        self.requested_doi: str | None = None

    def lookup_by_doi(self, doi: str) -> DiscoveryRecord:
        self.requested_doi = doi
        return self.record


def test_persist_candidate_is_idempotent_and_preserves_source_records(tmp_path: Path) -> None:
    repo = JsonWorkRepository(tmp_path / "works.json")
    service = WorkCatalogService(repo)
    records = (
        _record(
            "openalex",
            "W1",
            doi="10.1234/ABC",
            external_ids={"openalex": "W1", "doi": "10.1234/abc"},
        ),
        _record(
            "semantic-scholar",
            "S2-1",
            doi="https://doi.org/10.1234/abc",
            abstract="Provider abstract",
            external_ids={"DOI": "10.1234/abc", "CorpusId": "123"},
        ),
    )
    candidate = CanonicalIdentityResolver().resolve(records)[0]

    first = service.persist_candidate(candidate)
    second = service.persist_candidate(candidate)

    assert second.work_id == first.work_id
    assert second.abstract == "Provider abstract"
    identifiers = {(item.scheme, item.value) for item in repo.list_identifiers(first.work_id)}
    assert ("doi", "10.1234/abc") in identifiers
    assert ("openalex", "W1") in identifiers
    assert ("semantic-scholar", "S2-1") in identifiers
    assert len(repo.list_source_records(first.work_id)) == 2


def test_enrichment_fills_missing_metadata_without_overwriting_existing_values(
    tmp_path: Path,
) -> None:
    repo = JsonWorkRepository(tmp_path / "works.json")
    service = WorkCatalogService(repo)
    candidate = CanonicalIdentityResolver().resolve(
        (_record("openalex", "W1", doi="10.1234/abc", title="Chosen title", year=2024),)
    )[0]
    work = service.persist_candidate(candidate)
    enricher = _Enricher(
        _record(
            "crossref",
            "10.1234/abc",
            doi="10.1234/abc",
            title="Crossref title",
            year=2023,
            abstract="Crossref abstract",
            external_ids={"doi": "10.1234/abc", "issn": "1234-5678"},
            metadata={"publication_type": "journal-article", "venue": "Journal of Tests"},
        )
    )

    enriched = service.enrich_by_doi(work.work_id, enricher)

    assert enricher.requested_doi == "10.1234/abc"
    assert enriched.title == "Chosen title"
    assert enriched.publication_year == 2024
    assert enriched.abstract == "Crossref abstract"
    assert enriched.publication_type == "journal-article"
    assert enriched.venue == "Journal of Tests"
    identifiers = {(item.scheme, item.value) for item in repo.list_identifiers(work.work_id)}
    assert ("issn", "1234-5678") in identifiers
    assert len(repo.list_source_records(work.work_id)) == 2


def test_enrichment_rejects_doi_mismatch(tmp_path: Path) -> None:
    repo = JsonWorkRepository(tmp_path / "works.json")
    service = WorkCatalogService(repo)
    candidate = CanonicalIdentityResolver().resolve(
        (_record("openalex", "W1", doi="10.1234/abc"),)
    )[0]
    work = service.persist_candidate(candidate)

    with pytest.raises(WorkEnrichmentError, match="different DOI|returned DOI"):
        service.enrich_by_doi(
            work.work_id,
            _Enricher(_record("crossref", "10.9999/other", doi="10.9999/other")),
        )
