from __future__ import annotations

from collections.abc import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.citations import (
    BibliographicReference,
    CitationResolution,
    CitationResolutionStatus,
    WorkRelation,
    WorkRelationKind,
)
from tarkka.domain.identifiers import try_normalize_arxiv_id, try_normalize_doi
from tarkka.domain.source_observations import ObservationBasis
from tarkka.ports.works import WorkRepository


class CitationIdentityResolver:
    """Resolve bibliography entries only through exact canonical identifiers."""

    def __init__(
        self,
        repository: WorkRepository,
        *,
        id_factory: Callable[[str], UUID] | None = None,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory or _deterministic_id

    def resolve(self, reference: BibliographicReference) -> CitationResolution:
        matches: dict[UUID, str] = {}
        for scheme, raw_value in reference.identifiers.items():
            normalized_scheme = scheme.strip().lower()
            value = _normalize_identifier(normalized_scheme, raw_value)
            if value is None:
                continue
            work = self._repository.find_work_by_identifier(normalized_scheme, value)
            if work is not None:
                matches[work.work_id] = f"{normalized_scheme}:{value}"

        resolution_id = self._id_factory(f"citation-resolution:{reference.reference_id}")
        if not matches:
            return CitationResolution(
                resolution_id=resolution_id,
                reference_id=reference.reference_id,
                status=CitationResolutionStatus.UNRESOLVED,
                resolver="exact_identifier",
                source_observation_id=reference.source_observation_id,
            )
        if len(matches) > 1:
            return CitationResolution(
                resolution_id=resolution_id,
                reference_id=reference.reference_id,
                status=CitationResolutionStatus.AMBIGUOUS,
                candidate_work_ids=tuple(sorted(matches, key=str)),
                resolver="exact_identifier_conflict",
                source_observation_id=reference.source_observation_id,
            )
        work_id = next(iter(matches))
        return CitationResolution(
            resolution_id=resolution_id,
            reference_id=reference.reference_id,
            status=CitationResolutionStatus.RESOLVED,
            work_id=work_id,
            resolver="exact_identifier",
            source_observation_id=reference.source_observation_id,
        )

    def relation_for_resolved_reference(
        self,
        *,
        citing_work_id: UUID,
        reference: BibliographicReference,
        resolution: CitationResolution,
    ) -> WorkRelation:
        if resolution.reference_id != reference.reference_id:
            raise ValueError("citation resolution does not belong to reference")
        if (
            resolution.status is not CitationResolutionStatus.RESOLVED
            or resolution.work_id is None
        ):
            raise ValueError("citation relation requires a resolved reference")
        return WorkRelation(
            relation_id=self._id_factory(
                "work-relation:"
                f"{citing_work_id}:{resolution.work_id}:cites:{reference.reference_id}"
            ),
            subject_work_id=citing_work_id,
            object_work_id=resolution.work_id,
            kind=WorkRelationKind.CITES,
            basis=ObservationBasis.NATIVE,
            source_observation_id=reference.source_observation_id,
            source_document_id=reference.document_id,
            source_reference_id=reference.reference_id,
        )


def _normalize_identifier(scheme: str, value: str) -> str | None:
    stripped = value.strip()
    if not scheme or not stripped:
        return None
    if scheme == "doi":
        return try_normalize_doi(stripped)
    if scheme == "arxiv":
        return try_normalize_arxiv_id(stripped)
    return stripped


def _deterministic_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:{key}")
