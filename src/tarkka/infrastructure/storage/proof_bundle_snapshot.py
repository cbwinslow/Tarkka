"""Consistent local-JSON snapshots for proof-bundle creation."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from uuid import UUID

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.document_research_state import (
    DEFAULT_DOCUMENT_RESEARCH_STATE_LIMITS,
    DocumentResearchState,
    DocumentResearchStateLimits,
    assemble_document_research_state,
)
from tarkka.application.proof_bundles import (
    ProofBundleArtifactNotFoundError,
    ProofBundleSnapshot,
    ProofBundleV2Snapshot,
)
from tarkka.application.research_packages import ResearchPackageService
from tarkka.domain.extraction import Claim, ResearchObjectKind
from tarkka.domain.verification import EvidenceRelation
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.locking import exclusive_lock


class _EmptyEvidenceRelationReader:
    def page_relations(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        del claim_id, offset, limit
        return 0, ()


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
            return _read_source_snapshot_locked(
                document_id,
                documents=self._documents,
                observations=self._observations,
            )


class JsonProofBundleV2SnapshotReader:
    """Freeze source and Claim-lineage catalogs under one canonical local lock set."""

    def __init__(
        self,
        *,
        documents: JsonResearchRepository,
        observations: JsonSourceObservationRepository | None,
        extractions: JsonExtractionRepository | None,
        verifications: JsonVerificationRepository | None,
        citations: JsonCitationRepository | None,
        limits: DocumentResearchStateLimits = DEFAULT_DOCUMENT_RESEARCH_STATE_LIMITS,
    ) -> None:
        self._documents = documents
        self._observations = observations
        self._extractions = extractions
        self._verifications = verifications
        self._citations = citations
        self._limits = limits

    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None:
        with ExitStack() as stack:
            for path in _ordered_unique_paths(self._paths()):
                stack.enter_context(exclusive_lock(path))
            source = _read_source_snapshot_locked(
                document_id,
                documents=self._documents,
                observations=self._observations,
            )
            if source is None:
                return None
            return ProofBundleV2Snapshot(
                source=source,
                research_state=self._research_state_locked(document_id),
            )

    def _paths(self) -> list[Path]:
        paths = [self._documents.path]
        for repository in (
            self._observations,
            self._extractions,
            self._verifications,
            self._citations,
        ):
            if repository is not None:
                paths.append(repository.path)
        return paths

    def _research_state_locked(self, document_id: UUID) -> DocumentResearchState:
        if self._extractions is None:
            return DocumentResearchState(document_id=document_id, claim_lineages=())
        values = self._extractions.list_extractions(
            document_id,
            kind=ResearchObjectKind.CLAIM,
            offset=0,
            limit=self._limits.max_claims + 1,
        )
        claims: list[Claim] = []
        for value in values:
            if not isinstance(value, Claim):
                raise RuntimeError("Claim-filtered extraction read returned a non-Claim record")
            claims.append(value)
        service = ClaimLineageService(
            source=self._extractions,
            relations=(
                self._verifications
                if self._verifications is not None
                else _EmptyEvidenceRelationReader()
            ),
            documents=self._documents,
            citations=self._citations,
        )
        return assemble_document_research_state(
            document_id,
            tuple(claims),
            service,
            limits=self._limits,
        )


def _read_source_snapshot_locked(
    document_id: UUID,
    *,
    documents: JsonResearchRepository,
    observations: JsonSourceObservationRepository | None,
) -> ProofBundleSnapshot | None:
    document = documents.get_document(document_id)
    if document is None:
        return None
    artifact = documents.get_artifact(document.artifact_id)
    if artifact is None:
        raise ProofBundleArtifactNotFoundError(
            f"artifact not found for document {document_id}: {document.artifact_id}"
        )
    inspection = ResearchPackageService(
        documents=documents,
        work_documents=documents,
        observations=observations,
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
