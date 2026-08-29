"""Build portable proof-bundle payloads from existing canonical Tarkka state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from tarkka.application.research_packages import ResearchPackageService
from tarkka.domain.proof_bundles import (
    ProofBundleArtifact,
    ProofBundleDocument,
    ProofBundleManifest,
    ProofBundleResourceLink,
    ProofBundleSourceObservation,
    ProofBundleWorkDocumentLink,
    artifact_member_path,
)
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.repositories import ResearchRepository


class ProofBundleDocumentNotFoundError(LookupError):
    """Raised when a bundle is requested for an unknown normalized Document."""


class ProofBundleArtifactNotFoundError(LookupError):
    """Raised when a Document references an Artifact missing from the research catalog."""


class ProofBundleArtifactIntegrityError(RuntimeError):
    """Raised when preserved Artifact bytes do not match their immutable catalog identity."""


@dataclass(frozen=True, slots=True)
class ProofBundlePayload:
    """Validated manifest plus the exact immutable bytes embedded in a proof bundle."""

    manifest: ProofBundleManifest
    artifact_bytes: bytes


class ProofBundleService:
    """Compose an export payload without introducing new canonical research identities."""

    def __init__(
        self,
        *,
        documents: ResearchRepository,
        artifacts: ArtifactStore,
        packages: ResearchPackageService,
    ) -> None:
        self._documents = documents
        self._artifacts = artifacts
        self._packages = packages

    def build(self, document_id: UUID) -> ProofBundlePayload:
        document = self._documents.get_document(document_id)
        if document is None:
            raise ProofBundleDocumentNotFoundError(f"document not found: {document_id}")
        artifact = self._documents.get_artifact(document.artifact_id)
        if artifact is None:
            raise ProofBundleArtifactNotFoundError(
                f"artifact not found for document {document_id}: {document.artifact_id}"
            )

        artifact_bytes = self._artifacts.read_bytes(artifact)
        actual_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        if len(artifact_bytes) != artifact.size_bytes or actual_sha256 != artifact.sha256:
            raise ProofBundleArtifactIntegrityError(
                f"artifact bytes do not match immutable identity: {artifact.artifact_id}"
            )

        inspection = self._packages.inspect(document_id)
        if inspection.artifact_id != artifact.artifact_id:
            raise ProofBundleArtifactIntegrityError(
                "research package and document resolve to different artifacts"
            )

        manifest = ProofBundleManifest(
            document=ProofBundleDocument(
                document_id=document.document_id,
                artifact_id=document.artifact_id,
                title=document.title,
                parser_name=document.parser_name,
                parser_version=document.parser_version,
                normalized_at=document.normalized_at.isoformat(),
            ),
            artifact=ProofBundleArtifact(
                artifact_id=artifact.artifact_id,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                media_type=artifact.media_type,
                path=artifact_member_path(artifact.sha256),
                original_name=artifact.original_name,
                source_uri=artifact.source_uri,
                acquired_at=artifact.acquired_at.isoformat(),
            ),
            work_documents=tuple(
                ProofBundleWorkDocumentLink(
                    link_id=link.link_id,
                    work_id=link.work_id,
                    artifact_id=link.artifact_id,
                    document_id=link.document_id,
                    linked_at=link.linked_at.isoformat(),
                )
                for link in sorted(inspection.work_documents, key=lambda item: str(item.link_id))
            ),
            source_observations=tuple(
                ProofBundleSourceObservation(
                    observation_id=observation.observation_id,
                    source_name=observation.source_name,
                    basis=observation.basis.value,
                    source_version=observation.source_version,
                    provider_record_id=observation.provider_record_id,
                    media_type=observation.media_type,
                    native_artifact_id=observation.native_artifact_id,
                    metadata=observation.metadata,
                    observed_at=observation.observed_at.isoformat(),
                )
                for observation in sorted(
                    inspection.source_observations,
                    key=lambda item: str(item.observation_id),
                )
            ),
            resource_links=tuple(
                ProofBundleResourceLink(
                    link_id=link.link_id,
                    observation_id=link.observation_id,
                    target_uri=link.target_uri,
                    relation=link.relation.value,
                    media_type=link.media_type,
                    label=link.label,
                    metadata=link.metadata,
                )
                for link in sorted(inspection.resource_links, key=lambda item: str(item.link_id))
            ),
        )
        return ProofBundlePayload(manifest=manifest, artifact_bytes=artifact_bytes)
