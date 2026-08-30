from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Artifact, Document


class DocumentArtifactReader(Protocol):
    """Read only the normalized Document and immutable Artifact state needed for lineage."""

    def get_artifact(self, artifact_id: UUID) -> Artifact | None: ...

    def get_document(self, document_id: UUID) -> Document | None: ...


class ResearchRepository(DocumentArtifactReader, Protocol):
    def save_artifact(self, artifact: Artifact) -> None: ...

    def save_document(self, document: Document, manifest: ResourceManifest) -> None: ...

    def get_manifest(self, document_id: UUID) -> ResourceManifest | None: ...
