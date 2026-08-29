"""Consistent local-JSON snapshots for proof-bundle creation."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from uuid import UUID

from tarkka.application.proof_bundles import (
    ProofBundleArtifactNotFoundError,
    ProofBundleSnapshot,
)
from tarkka.application.research_packages import ResearchPackageService
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonProofBundleSnapshotReader:
    """Read catalog and observation JSON files under one deterministic lock set."""

    def __init__(
        self,
        *,
        documents: JsonResearchRepository,
        observations: JsonSourceObservationRepository | None,
    ) -> None:
        self._documents = documents
        self._observations = observations

    def read(self, document_id: UUID) -> ProofBundleSnapshot | None:
        paths = [self._documents.path]
        if self._observations is not None:
            paths.append(self._observations.path)
        with ExitStack() as stack:
            for path in _ordered_unique_paths(paths):
                stack.enter_context(exclusive_lock(path))
            document = self._documents.get_document(document_id)
            if document is None:
                return None
            artifact = self._documents.get_artifact(document.artifact_id)
            if artifact is None:
                raise ProofBundleArtifactNotFoundError(
                    f"artifact not found for document {document_id}: {document.artifact_id}"
                )
            inspection = ResearchPackageService(
                documents=self._documents,
                work_documents=self._documents,
                observations=self._observations,
            ).inspect(document_id)
            if inspection.artifact_id != artifact.artifact_id:
                raise RuntimeError("locked research-package snapshot resolved another artifact")
            return ProofBundleSnapshot(
                document=document,
                artifact=artifact,
                work_documents=inspection.work_documents,
                source_observations=inspection.source_observations,
                resource_links=inspection.resource_links,
            )


def _ordered_unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    """Acquire multiple catalog locks in canonical order to avoid lock inversion."""
    return tuple(sorted({path.expanduser().resolve() for path in paths}, key=str))
