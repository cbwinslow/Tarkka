from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from tarkka.application.citation_resolution import CitationResolutionService
from tarkka.domain.citations import (
    BibliographicReference,
    CitationResolutionStatus,
    WorkRelationKind,
)
from tarkka.domain.models import Work
from tarkka.domain.source_observations import ObservationBasis
from tarkka.domain.work_identity import WorkIdentifier
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository


def _repositories(tmp_path: Path) -> tuple[JsonCitationRepository, JsonWorkRepository]:
    return (
        JsonCitationRepository(tmp_path / "citations.json"),
        JsonWorkRepository(tmp_path / "works.json"),
    )


def _save_work_with_identifier(
    repository: JsonWorkRepository,
    *,
    title: str,
    scheme: str,
    value: str,
) -> Work:
    work = Work(work_id=uuid4(), title=title)
    with repository.transaction():
        repository.save_work(work)
        repository.save_identifier(
            WorkIdentifier(
                identifier_id=uuid4(),
                work_id=work.work_id,
                scheme=scheme,
                value=value,
            )
        )
    return work


def test_reference_resolves_by_normalized_doi_and_is_idempotent(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    target = _save_work_with_identifier(
        works,
        title="Resolved target",
        scheme="doi",
        value="10.1000/example",
    )
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Resolved target. doi:10.1000/example",
        identifiers={"DOI": "https://doi.org/10.1000/EXAMPLE"},
    )
    citations.save_reference(reference)
    service = CitationResolutionService(citations, works)

    first = service.resolve_reference(reference)
    second = service.resolve_reference(reference)

    assert first.status is CitationResolutionStatus.RESOLVED
    assert first.work_id == target.work_id
    assert second == first
    assert citations.get_resolution(reference.reference_id) == first


def test_conflicting_exact_identifiers_remain_ambiguous(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    doi_work = _save_work_with_identifier(
        works,
        title="DOI target",
        scheme="doi",
        value="10.1000/ambiguous",
    )
    arxiv_work = _save_work_with_identifier(
        works,
        title="arXiv target",
        scheme="arxiv",
        value="2401.12345",
    )
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Ambiguous reference",
        identifiers={"doi": "10.1000/ambiguous", "arxiv": "arXiv:2401.12345v2"},
    )
    citations.save_reference(reference)

    resolution = CitationResolutionService(citations, works).resolve_reference(reference)

    assert resolution.status is CitationResolutionStatus.AMBIGUOUS
    assert resolution.work_id is None
    assert set(resolution.candidate_work_ids) == {doi_work.work_id, arxiv_work.work_id}


def test_unknown_and_invalid_identifiers_remain_unresolved(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="No canonical match",
        identifiers={"doi": "not-a-doi", "pmid": "123456"},
    )
    citations.save_reference(reference)

    resolution = CitationResolutionService(citations, works).resolve_reference(reference)

    assert resolution.status is CitationResolutionStatus.UNRESOLVED
    assert resolution.work_id is None
    assert resolution.candidate_work_ids == ()


def test_document_resolution_creates_native_cites_relation_once(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    citing = Work(work_id=uuid4(), title="Citing work")
    with works.transaction():
        works.save_work(citing)
    cited = _save_work_with_identifier(
        works,
        title="Cited work",
        scheme="doi",
        value="10.1000/cited",
    )
    document_id = uuid4()
    observation_id = uuid4()
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=0,
        raw_text="Cited work",
        identifiers={"doi": "10.1000/cited"},
        source_observation_id=observation_id,
    )
    citations.save_reference(reference)
    service = CitationResolutionService(citations, works)

    first = service.resolve_document(document_id, citing_work_id=citing.work_id)
    second = service.resolve_document(document_id, citing_work_id=citing.work_id)

    assert len(first.relations) == 1
    relation = first.relations[0]
    assert relation == second.relations[0]
    assert relation.subject_work_id == citing.work_id
    assert relation.object_work_id == cited.work_id
    assert relation.kind is WorkRelationKind.CITES
    assert relation.basis is ObservationBasis.NATIVE
    assert relation.source_document_id == document_id
    assert relation.source_reference_id == reference.reference_id
    assert relation.source_observation_id == observation_id
    assert citations.list_relations_from(citing.work_id) == (relation,)
