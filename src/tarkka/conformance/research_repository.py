from __future__ import annotations

from uuid import UUID

from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Artifact, Document
from tarkka.ports.repositories import ResearchRepository


class ResearchRepositoryContract:
    """Reusable behavioral assertions for any ``ResearchRepository`` implementation."""

    @staticmethod
    def assert_missing_reads_return_none(repository: ResearchRepository) -> None:
        missing = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

        assert repository.get_artifact(missing) is None
        assert repository.get_document(missing) is None
        assert repository.get_manifest(missing) is None

    @staticmethod
    def assert_artifact_round_trip(
        repository: ResearchRepository,
        artifact: Artifact,
    ) -> None:
        repository.save_artifact(artifact)

        assert repository.get_artifact(artifact.artifact_id) == artifact

    @staticmethod
    def assert_document_manifest_round_trip(
        repository: ResearchRepository,
        document: Document,
        manifest: ResourceManifest,
    ) -> None:
        repository.save_document(document, manifest)

        assert repository.get_document(document.document_id) == document
        assert repository.get_manifest(document.document_id) == manifest

    @staticmethod
    def assert_repeated_saves_are_idempotent(
        repository: ResearchRepository,
        artifact: Artifact,
        document: Document,
        manifest: ResourceManifest,
    ) -> None:
        repository.save_artifact(artifact)
        repository.save_artifact(artifact)
        repository.save_document(document, manifest)
        repository.save_document(document, manifest)

        assert repository.get_artifact(artifact.artifact_id) == artifact
        assert repository.get_document(document.document_id) == document
        assert repository.get_manifest(document.document_id) == manifest
