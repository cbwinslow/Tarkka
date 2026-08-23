"""Reusable fault-injecting test adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Artifact, Document
from tarkka.ports.repositories import ResearchRepository
from tests.support.deterministic import FaultPlan


@dataclass(slots=True)
class FaultInjectingResearchRepository:
    """Delegate to a repository while injecting deterministic persistence failures."""

    inner: ResearchRepository
    save_artifact_fault: FaultPlan = field(default_factory=FaultPlan)
    save_document_fault: FaultPlan = field(default_factory=FaultPlan)

    def save_artifact(self, artifact: Artifact) -> None:
        self.save_artifact_fault.checkpoint()
        self.inner.save_artifact(artifact)

    def save_document(self, document: Document, manifest: ResourceManifest) -> None:
        self.save_document_fault.checkpoint()
        self.inner.save_document(document, manifest)

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        return self.inner.get_artifact(artifact_id)

    def get_document(self, document_id: UUID) -> Document | None:
        return self.inner.get_document(document_id)

    def get_manifest(self, document_id: UUID) -> ResourceManifest | None:
        return self.inner.get_manifest(document_id)
