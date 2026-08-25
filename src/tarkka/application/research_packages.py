"""Progressive inspection of resources observed for a parsed Work representation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.research_packages import ArtifactSourceObservationRepository
from tarkka.ports.work_documents import WorkDocumentRepository

MAX_RESOURCE_LINK_OFFSET = 10_000
MAX_RESOURCE_LINK_PAGE_SIZE = 100


class ResearchPackageNotFoundError(LookupError):
    """Raised when package inspection is requested for an unknown Document."""


class ResourceLinkNotFoundError(LookupError):
    """Raised when an exact resource-link handle is not observed for a Document."""


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


@dataclass(frozen=True, slots=True)
class ResourceLinkPage:
    """A bounded page of compact source-observed resource-link manifests."""

    document_id: UUID
    artifact_id: UUID
    total: int
    resource_links: tuple[ResourceLinkManifest, ...]


@dataclass(frozen=True, slots=True)
class ResourceLinkManifest:
    """Compact resource-link routing metadata; native metadata expands separately."""

    link_id: UUID
    observation_id: UUID
    relation: str
    target_uri: str
    media_type: str | None
    label: str | None
    metadata_keys: tuple[str, ...]


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

    def resource_links(
        self,
        document_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> ResourceLinkPage:
        """Return a bounded page of source-observed resource links for one Document."""
        if offset < 0 or limit < 0:
            raise ValueError("resource offset and limit must be non-negative")
        if offset > MAX_RESOURCE_LINK_OFFSET or limit > MAX_RESOURCE_LINK_PAGE_SIZE:
            raise ValueError("resource pagination exceeds the configured maximum")
        document = self._documents.get_document(document_id)
        if document is None:
            raise ResearchPackageNotFoundError(f"document not found: {document_id}")
        repository = self._observations
        total: int
        resource_links: tuple[ResourceLinkObservation, ...]
        if repository is None:
            total, resource_links = 0, ()
        else:
            total, resource_links = repository.page_resource_links_for_artifact(
                document.artifact_id,
                offset=offset,
                limit=limit,
            )
        return ResourceLinkPage(
            document_id=document.document_id,
            artifact_id=document.artifact_id,
            total=total,
            resource_links=tuple(_resource_link_manifest(link) for link in resource_links),
        )

    def resource_link(self, document_id: UUID, link_id: UUID) -> ResourceLinkObservation:
        """Expand one exact source-observed resource link without resolving its target."""
        document = self._documents.get_document(document_id)
        if document is None:
            raise ResearchPackageNotFoundError(f"document not found: {document_id}")
        repository = self._observations
        if repository is not None:
            resource_link = repository.get_resource_link_for_artifact(document.artifact_id, link_id)
            if resource_link is not None:
                return resource_link
        raise ResourceLinkNotFoundError(f"resource link not found: {link_id}")


def _resource_link_manifest(link: ResourceLinkObservation) -> ResourceLinkManifest:
    return ResourceLinkManifest(
        link_id=link.link_id,
        observation_id=link.observation_id,
        relation=link.relation.value,
        target_uri=link.target_uri,
        media_type=link.media_type,
        label=link.label,
        metadata_keys=tuple(sorted(link.metadata)),
    )
