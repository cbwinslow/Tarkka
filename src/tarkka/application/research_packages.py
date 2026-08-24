"""Progressive inspection of resources observed for a parsed Work representation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.research_packages import ArtifactSourceObservationRepository
from tarkka.ports.work_documents import WorkDocumentRepository


class ResearchPackageNotFoundError(LookupError):
    """Raised when package inspection is requested for an unknown Document."""


@dataclass(frozen=True, slots=True)
class ResearchPackageInspection:
    """Bounded composition of preserved resource links around one Document.

    This is an inspection result, not a new canonical identity or relation model. Resource
    targets remain source-observed URIs until an explicit later acquisition/resolution step.
    """

    document_id: UUID
    artifact_id: UUID
    work_documents: tuple[WorkDocumentLink, ...]
    source_observations: tuple[SourceObservation, ...]
    resource_links: tuple[ResourceLinkObservation, ...]


class ResearchPackageService:
    """Group resource observations through a Document's immutable source Artifact."""

    def __init__(
        self,
        *,
        documents: ResearchRepository,
        work_documents: WorkDocumentRepository,
        observations: ArtifactSourceObservationRepository | None = None,
    ) -> None:
        self._documents = documents
        self._work_documents = work_documents
        self._observations = observations

    def inspect(self, document_id: UUID) -> ResearchPackageInspection:
        document = self._documents.get_document(document_id)
        if document is None:
            raise ResearchPackageNotFoundError(f"document not found: {document_id}")

        repository = self._observations
        if repository is None:
            observations: tuple[SourceObservation, ...] = ()
            resource_links: tuple[ResourceLinkObservation, ...] = ()
        else:
            observations = repository.list_observations_for_artifact(document.artifact_id)
            resource_links = tuple(
                link
                for observation in observations
                for link in repository.list_resource_links(observation.observation_id)
            )
        return ResearchPackageInspection(
            document_id=document.document_id,
            artifact_id=document.artifact_id,
            work_documents=self._work_documents.list_document_work_links(document.document_id),
            source_observations=observations,
            resource_links=resource_links,
        )
