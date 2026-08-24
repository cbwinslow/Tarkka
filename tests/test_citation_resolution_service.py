from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.application.citation_resolution import (
    AmbiguousCitingWorkError,
    CitationResolutionService,
)
from tarkka.domain.citations import (
    BibliographicReference,
    CitationResolutionStatus,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.models import Work
from tarkka.domain.source_observations import ObservationBasis
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.domain.work_identity import WorkIdentifier
from tarkka.infrastructure.storage.json_citation_repository import (
    CitationConflictError,
    JsonCitationRepository,
)
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


class _DocumentLinks:
    def __init__(self, links: tuple[WorkDocumentLink, ...]) -> None:
        self._links = links

    def list_work_document_links(self, work_id: UUID) -> tuple[WorkDocumentLink, ...]:
        return tuple(link for link in self._links if link.work_id == work_id)

    def save_work_document_link(self, link: WorkDocumentLink) -> None:
        self._links = (*self._links, link)

    def list_document_work_links(self, document_id: UUID) -> tuple[WorkDocumentLink, ...]:
        return tuple(link for link in self._links if link.document_id == document_id)


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


def test_exact_non_specialized_identifier_resolves(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    target = _save_work_with_identifier(
        works,
        title="PMID target",
        scheme="pmid",
        value="123456",
    )
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="PMID target",
        identifiers={"PMID": "123456"},
    )
    citations.save_reference(reference)

    resolution = CitationResolutionService(citations, works).resolve_reference(reference)

    assert resolution.status is CitationResolutionStatus.RESOLVED
    assert resolution.work_id == target.work_id


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
    assert citations.get_relation(relation.relation_id) == relation
    assert citations.list_relations_from(citing.work_id) == (relation,)


def test_document_resolution_infers_one_persisted_citing_work_link(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    citing = Work(work_id=uuid4(), title="Citing work")
    with works.transaction():
        works.save_work(citing)
    cited = _save_work_with_identifier(
        works,
        title="Cited work",
        scheme="doi",
        value="10.1000/inferred-citing-work",
    )
    document_id = uuid4()
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document_id,
        ordinal=0,
        raw_text="Cited work",
        identifiers={"doi": "10.1000/inferred-citing-work"},
    )
    citations.save_reference(reference)
    links = _DocumentLinks(
        (
            WorkDocumentLink(
                link_id=uuid4(),
                work_id=citing.work_id,
                artifact_id=uuid4(),
                document_id=document_id,
            ),
        )
    )

    result = CitationResolutionService(citations, works, work_documents=links).resolve_document(
        document_id
    )

    assert result.citing_work_id == citing.work_id
    assert result.relations[0].subject_work_id == citing.work_id
    assert result.relations[0].object_work_id == cited.work_id


def test_document_resolution_refuses_to_guess_among_multiple_work_links(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    document_id = uuid4()
    links = _DocumentLinks(
        tuple(
            WorkDocumentLink(
                link_id=uuid4(),
                work_id=uuid4(),
                artifact_id=uuid4(),
                document_id=document_id,
            )
            for _ in range(2)
        )
    )

    with pytest.raises(AmbiguousCitingWorkError, match="multiple canonical Work links"):
        CitationResolutionService(citations, works, work_documents=links).resolve_document(
            document_id
        )


def test_document_resolution_without_citing_work_or_link_resolves_without_relations(
    tmp_path: Path,
) -> None:
    citations, works = _repositories(tmp_path)

    result = CitationResolutionService(citations, works).resolve_document(uuid4())

    assert result.citing_work_id is None
    assert result.relations == ()


def test_document_resolution_with_no_persisted_work_links_does_not_guess(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)

    result = CitationResolutionService(
        citations,
        works,
        work_documents=_DocumentLinks(()),
    ).resolve_document(uuid4())

    assert result.citing_work_id is None


def test_document_resolution_rejects_unknown_explicit_or_inferred_citing_work(
    tmp_path: Path,
) -> None:
    citations, works = _repositories(tmp_path)
    document_id = uuid4()
    unknown = uuid4()

    with pytest.raises(ValueError, match="citing work not found"):
        CitationResolutionService(citations, works).resolve_document(
            document_id,
            citing_work_id=unknown,
        )
    with pytest.raises(ValueError, match="citing work not found"):
        CitationResolutionService(
            citations,
            works,
            work_documents=_DocumentLinks(
                (
                    WorkDocumentLink(
                        link_id=uuid4(),
                        work_id=unknown,
                        artifact_id=uuid4(),
                        document_id=document_id,
                    ),
                )
            ),
        ).resolve_document(document_id)


def test_explicit_citing_work_must_match_persisted_document_links(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    document_id = uuid4()
    linked = Work(work_id=uuid4(), title="Linked work")
    other = Work(work_id=uuid4(), title="Other work")
    with works.transaction():
        works.save_work(linked)
        works.save_work(other)
    links = _DocumentLinks(
        (
            WorkDocumentLink(
                link_id=uuid4(),
                work_id=linked.work_id,
                artifact_id=uuid4(),
                document_id=document_id,
            ),
        )
    )

    with pytest.raises(ValueError, match="not linked to the source document"):
        CitationResolutionService(citations, works, work_documents=links).resolve_document(
            document_id,
            citing_work_id=other.work_id,
        )


def test_document_resolution_paginates_references_before_resolving(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    document_id = uuid4()
    for ordinal in range(3):
        citations.save_reference(
            BibliographicReference(
                reference_id=uuid4(),
                document_id=document_id,
                ordinal=ordinal,
                raw_text=f"Reference {ordinal}",
            )
        )

    result = CitationResolutionService(citations, works).resolve_document(
        document_id,
        offset=1,
        limit=1,
    )

    assert result.total_references == 3
    assert [item.reference_id for item in result.resolutions] == [
        citations.list_references(document_id, offset=1, limit=1)[0].reference_id
    ]


def test_document_resolution_rejects_conflicting_relation_provenance(tmp_path: Path) -> None:
    citations, works = _repositories(tmp_path)
    citing = Work(work_id=uuid4(), title="Citing work")
    with works.transaction():
        works.save_work(citing)
    cited = _save_work_with_identifier(
        works,
        title="Cited work",
        scheme="doi",
        value="10.1000/conflict",
    )
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Cited work",
        identifiers={"doi": "10.1000/conflict"},
        source_observation_id=uuid4(),
    )
    citations.save_reference(reference)
    relation_id = uuid5(
        NAMESPACE_URL,
        f"tarkka:cites:{citing.work_id}:{reference.reference_id}:{cited.work_id}",
    )
    citations.save_relation(
        WorkRelation(
            relation_id=relation_id,
            subject_work_id=citing.work_id,
            object_work_id=cited.work_id,
            kind=WorkRelationKind.CITES,
            basis=ObservationBasis.NATIVE,
            source_observation_id=uuid4(),
            source_document_id=reference.document_id,
            source_reference_id=reference.reference_id,
        )
    )

    with pytest.raises(CitationConflictError, match="conflicting relation"):
        CitationResolutionService(citations, works).resolve_document(
            reference.document_id,
            citing_work_id=citing.work_id,
        )
