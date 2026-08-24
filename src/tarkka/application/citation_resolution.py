from __future__ import annotations

from dataclasses import dataclass
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
from tarkka.ports.citations import CitationRepository
from tarkka.ports.work_documents import WorkDocumentRepository
from tarkka.ports.works import WorkRepository

_RESOLVER_NAME = "canonical-identifiers-v1"


@dataclass(frozen=True, slots=True)
class CitationResolutionResult:
    resolutions: tuple[CitationResolution, ...]
    relations: tuple[WorkRelation, ...]
    citing_work_id: UUID | None
    total_references: int


class AmbiguousCitingWorkError(ValueError):
    """A Document must not silently choose among multiple canonical Work links."""


class CitationResolutionService:
    """Resolve preserved references through exact canonical identifiers only."""

    def __init__(
        self,
        citations: CitationRepository,
        works: WorkRepository,
        work_documents: WorkDocumentRepository | None = None,
    ) -> None:
        self._citations = citations
        self._works = works
        self._work_documents = work_documents

    def resolve_reference(self, reference: BibliographicReference) -> CitationResolution:
        matched_work_ids = self._matched_work_ids(reference)
        if len(matched_work_ids) == 1:
            resolution = CitationResolution(
                resolution_id=_resolution_id(reference.reference_id),
                reference_id=reference.reference_id,
                status=CitationResolutionStatus.RESOLVED,
                work_id=matched_work_ids[0],
                resolver=_RESOLVER_NAME,
                source_observation_id=reference.source_observation_id,
            )
        elif len(matched_work_ids) > 1:
            resolution = CitationResolution(
                resolution_id=_resolution_id(reference.reference_id),
                reference_id=reference.reference_id,
                status=CitationResolutionStatus.AMBIGUOUS,
                candidate_work_ids=matched_work_ids,
                resolver=_RESOLVER_NAME,
                source_observation_id=reference.source_observation_id,
            )
        else:
            resolution = CitationResolution(
                resolution_id=_resolution_id(reference.reference_id),
                reference_id=reference.reference_id,
                status=CitationResolutionStatus.UNRESOLVED,
                resolver=_RESOLVER_NAME,
                source_observation_id=reference.source_observation_id,
            )

        existing = self._citations.get_resolution(reference.reference_id)
        if existing is not None and _same_resolution(existing, resolution):
            return existing
        self._citations.save_resolution(resolution)
        return resolution

    def resolve_document(
        self,
        document_id: UUID,
        *,
        citing_work_id: UUID | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> CitationResolutionResult:
        if offset < 0 or limit is not None and limit < 0:
            raise ValueError("citation resolution offset and limit must be non-negative")
        effective_citing_work_id = self._citing_work_id(document_id, citing_work_id)

        resolutions: list[CitationResolution] = []
        relations: list[WorkRelation] = []
        for reference in self._citations.list_references(
            document_id,
            offset=offset,
            limit=limit,
        ):
            resolution = self.resolve_reference(reference)
            resolutions.append(resolution)
            if effective_citing_work_id is None or resolution.work_id is None:
                continue
            relation = self._cites_relation(
                effective_citing_work_id,
                reference,
                resolution.work_id,
            )
            relations.append(relation)
        return CitationResolutionResult(
            tuple(resolutions),
            tuple(relations),
            effective_citing_work_id,
            self._citations.count_references(document_id),
        )

    def _citing_work_id(self, document_id: UUID, explicit: UUID | None) -> UUID | None:
        if explicit is not None:
            if self._works.get_work(explicit) is None:
                raise ValueError(f"citing work not found: {explicit}")
            if self._work_documents is not None:
                linked_work_ids = {
                    link.work_id
                    for link in self._work_documents.list_document_work_links(document_id)
                }
                if linked_work_ids and explicit not in linked_work_ids:
                    raise ValueError(
                        "explicit citing work is not linked to the source document"
                    )
            return explicit
        if self._work_documents is None:
            return None
        candidate_ids = {
            link.work_id for link in self._work_documents.list_document_work_links(document_id)
        }
        if len(candidate_ids) > 1:
            raise AmbiguousCitingWorkError(
                "document has multiple canonical Work links; specify citing_work_id explicitly"
            )
        if not candidate_ids:
            return None
        inferred = next(iter(candidate_ids))
        if self._works.get_work(inferred) is None:
            raise ValueError(f"citing work not found: {inferred}")
        return inferred

    def _matched_work_ids(self, reference: BibliographicReference) -> tuple[UUID, ...]:
        matched: set[UUID] = set()
        for raw_scheme, raw_value in reference.identifiers.items():
            normalized = _normalized_identifier(raw_scheme, raw_value)
            if normalized is None:
                continue
            scheme, value = normalized
            work = self._works.find_work_by_identifier(scheme, value)
            if work is not None:
                matched.add(work.work_id)
        return tuple(sorted(matched, key=str))

    def _cites_relation(
        self,
        citing_work_id: UUID,
        reference: BibliographicReference,
        cited_work_id: UUID,
    ) -> WorkRelation:
        relation = WorkRelation(
            relation_id=uuid5(
                NAMESPACE_URL,
                f"tarkka:cites:{citing_work_id}:{reference.reference_id}:{cited_work_id}",
            ),
            subject_work_id=citing_work_id,
            object_work_id=cited_work_id,
            kind=WorkRelationKind.CITES,
            basis=ObservationBasis.NATIVE,
            source_observation_id=reference.source_observation_id,
            source_document_id=reference.document_id,
            source_reference_id=reference.reference_id,
        )
        return self._citations.get_or_create_relation(relation)


def _resolution_id(reference_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:citation-resolution:{reference_id}")


def _normalized_identifier(scheme: str, value: str) -> tuple[str, str] | None:
    normalized_scheme = scheme.strip().lower()
    normalized_value = value.strip()
    if not normalized_scheme or not normalized_value:
        return None
    if normalized_scheme == "doi":
        doi = try_normalize_doi(normalized_value)
        return ("doi", doi) if doi is not None else None
    if normalized_scheme == "arxiv":
        arxiv_id = try_normalize_arxiv_id(normalized_value)
        return ("arxiv", arxiv_id) if arxiv_id is not None else None
    # Other schemes intentionally use exact canonical values. Their ingestion adapter owns
    # scheme-specific normalization until a shared normalizer is explicitly defined.
    return normalized_scheme, normalized_value


def _same_resolution(left: CitationResolution, right: CitationResolution) -> bool:
    # resolved_at is event metadata, not resolution identity. Ignoring it makes repeated
    # deterministic resolution idempotent and preserves the timestamp of the first result.
    return (
        left.resolution_id == right.resolution_id
        and left.reference_id == right.reference_id
        and left.status is right.status
        and left.work_id == right.work_id
        and left.candidate_work_ids == right.candidate_work_ids
        and left.resolver == right.resolver
        and left.source_observation_id == right.source_observation_id
    )
