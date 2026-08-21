from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.citations import CitationIdentityResolver
from tarkka.domain.citations import BibliographicReference, CitationResolutionStatus
from tarkka.domain.models import Work
from tarkka.ports.works import WorkRepository


@dataclass
class _IdentifierLookup:
    matches: dict[tuple[str, str], Work]

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None:
        return self.matches.get((scheme, value))


def _work() -> Work:
    return Work(work_id=uuid4(), title="Example")


def _reference(**identifiers: str) -> BibliographicReference:
    return BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Example reference",
        identifiers=identifiers,
        source_observation_id=uuid4(),
    )


def _resolver(matches: dict[tuple[str, str], Work]) -> CitationIdentityResolver:
    repository = cast(WorkRepository, _IdentifierLookup(matches))
    return CitationIdentityResolver(repository)


def test_exact_doi_resolution_uses_canonical_normalization() -> None:
    work = _work()
    reference = _reference(doi="https://doi.org/10.1000/EXAMPLE")

    resolution = _resolver({("doi", "10.1000/example"): work}).resolve(reference)

    assert resolution.status is CitationResolutionStatus.RESOLVED
    assert resolution.work_id == work.work_id
    assert resolution.resolver == "exact_identifier"
    assert resolution.source_observation_id == reference.source_observation_id


def test_unknown_identifier_remains_unresolved() -> None:
    resolution = _resolver({}).resolve(_reference(doi="10.1000/example"))

    assert resolution.status is CitationResolutionStatus.UNRESOLVED
    assert resolution.work_id is None


def test_conflicting_exact_identifiers_fail_closed_as_ambiguous() -> None:
    doi_work = _work()
    arxiv_work = _work()
    reference = _reference(doi="10.1000/example", arxiv="2401.01234v2")

    resolution = _resolver(
        {
            ("doi", "10.1000/example"): doi_work,
            ("arxiv", "2401.01234"): arxiv_work,
        }
    ).resolve(reference)

    assert resolution.status is CitationResolutionStatus.AMBIGUOUS
    assert resolution.work_id is None
    assert set(resolution.candidate_work_ids) == {doi_work.work_id, arxiv_work.work_id}


def test_multiple_exact_identifiers_for_same_work_resolve_once() -> None:
    work = _work()
    reference = _reference(doi="10.1000/example", arxiv="2401.01234")

    resolution = _resolver(
        {
            ("doi", "10.1000/example"): work,
            ("arxiv", "2401.01234"): work,
        }
    ).resolve(reference)

    assert resolution.status is CitationResolutionStatus.RESOLVED
    assert resolution.work_id == work.work_id


def test_resolved_reference_creates_provenance_backed_cites_relation() -> None:
    cited = _work()
    citing_id = uuid4()
    reference = _reference(doi="10.1000/example")
    resolver = _resolver({("doi", "10.1000/example"): cited})
    resolution = resolver.resolve(reference)

    relation = resolver.relation_for_resolved_reference(
        citing_work_id=citing_id,
        reference=reference,
        resolution=resolution,
    )

    assert relation.subject_work_id == citing_id
    assert relation.object_work_id == cited.work_id
    assert relation.source_document_id == reference.document_id
    assert relation.source_reference_id == reference.reference_id
    assert relation.source_observation_id == reference.source_observation_id


def test_relation_rejects_unresolved_or_mismatched_resolution() -> None:
    reference = _reference(doi="10.1000/example")
    resolver = _resolver({})
    unresolved = resolver.resolve(reference)

    with pytest.raises(ValueError, match="resolved reference"):
        resolver.relation_for_resolved_reference(
            citing_work_id=uuid4(),
            reference=reference,
            resolution=unresolved,
        )

    cited = _work()
    other_reference = _reference(doi="10.1000/example")
    resolved = _resolver({("doi", "10.1000/example"): cited}).resolve(other_reference)
    with pytest.raises(ValueError, match="does not belong"):
        resolver.relation_for_resolved_reference(
            citing_work_id=uuid4(),
            reference=reference,
            resolution=resolved,
        )


def test_resolution_ids_are_stable_for_same_reference() -> None:
    reference = _reference(doi="10.1000/example")
    resolver = _resolver({})

    first: UUID = resolver.resolve(reference).resolution_id
    second: UUID = resolver.resolve(reference).resolution_id

    assert first == second
