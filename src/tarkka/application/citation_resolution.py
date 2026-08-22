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
from tarkka.ports.works import WorkRepository

_RESOLVER_NAME = "canonical-identifiers-v1"


@dataclass(frozen=True, slots=True)
class CitationResolutionResult:
    resolutions: tuple[CitationResolution, ...]
    relations: tuple[WorkRelation, ...]


class CitationResolutionService:
    """Resolve preserved references through exact canonical identifiers only.

    Repository implementations are responsible for serializing writes to a reference's
    resolution key. Production SQL adapters should enforce this with a unique constraint and
    transactional/upsert semantics; the local JSON repository provides the same serialization
    with its file lock.
    """

    def __init__(
        self,
        citations: CitationRepository,
        works: WorkRepository,
    ) -> None:
        self._citations = citations
        self._works = works

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
    ) -> CitationResolutionResult:
        if citing_work_id is not None and self._works.get_work(citing_work_id) is None:
            raise ValueError(f"citing work not found: {citing_work_id}")

        resolutions: list[CitationResolution] = []
        relations: list[WorkRelation] = []
        for reference in self._citations.list_references(document_id):
            resolution = self.resolve_reference(reference)
            resolutions.append(resolution)
            if citing_work_id is None or resolution.work_id is None:
                continue
            relation = self._cites_relation(citing_work_id, reference, resolution.work_id)
            relations.append(relation)
        return CitationResolutionResult(tuple(resolutions), tuple(relations))

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
        relation_id = uuid5(
            NAMESPACE_URL,
            f"tarkka:cites:{citing_work_id}:{reference.reference_id}:{cited_work_id}",
        )
        existing = self._citations.get_relation(relation_id)
        if existing is not None:
            # The deterministic relation ID already includes the reference, so repeated
            # resolution should reuse its original provenance instead of manufacturing a
            # second edge with the same semantic identity.
            return existing
        relation = WorkRelation(
            relation_id=relation_id,
            subject_work_id=citing_work_id,
            object_work_id=cited_work_id,
            kind=WorkRelationKind.CITES,
            basis=ObservationBasis.NATIVE,
            source_observation_id=reference.source_observation_id,
            source_document_id=reference.document_id,
            source_reference_id=reference.reference_id,
        )
        self._citations.save_relation(relation)
        return relation


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
        left.reference_id == right.reference_id
        and left.status is right.status
        and left.work_id == right.work_id
        and left.candidate_work_ids == right.candidate_work_ids
        and left.resolver == right.resolver
        and left.source_observation_id == right.source_observation_id
    )
