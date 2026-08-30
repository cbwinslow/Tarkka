"""Consistent local-JSON snapshots for proof-bundle creation."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from uuid import UUID

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.proof_bundle_research_state import (
    ProofBundleResearchStateLimits,
    collect_document_claim_lineages,
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


class JsonProofBundleSnapshotReader:
    """Read v1 catalog and observation JSON files under one deterministic lock set."""

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
            return _read_source_snapshot(
                document_id,
                documents=self._documents,
                observations=self._observations,
            )


class JsonProofBundleV2SnapshotReader:
    """Read source and complete Claim state under one canonical JSON lock set."""

    def __init__(
        self,
        *,
        documents: JsonResearchRepository,
        observations: JsonSourceObservationRepository | None,
        extractions: JsonExtractionRepository | None,
        verifications: JsonVerificationRepository | None,
        citations: JsonCitationRepository | None,
        limits: ProofBundleResearchStateLimits = ProofBundleResearchStateLimits(),
    ) -> None:
        self._documents = documents
        self._observations = observations
        self._extractions = extractions
        self._verifications = verifications
        self._citations = citations
        self._limits = limits

    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None:
        repositories = (
            self._documents,
            self._observations,
            self._extractions,
            self._verifications,
            self._citations,
        )
        paths = [repository.path for repository in repositories if repository is not None]
        with ExitStack() as stack:
            for path in _ordered_unique_paths(paths):
                stack.enter_context(exclusive_lock(path))
            source = _read_source_snapshot(
                document_id,
                documents=self._documents,
                observations=self._observations,
            )
            if source is None:
                return None
            if self._extractions is None:
                return ProofBundleV2Snapshot(source=source)

            records = self._extractions.list_extractions(
                document_id,
                kind=ResearchObjectKind.CLAIM,
                offset=0,
                limit=self._limits.max_claims + 1,
            )
            claims = tuple(item for item in records if isinstance(item, Claim))
            service = ClaimLineageService(
                source=self._extractions,
                relations=self._verifications or _EmptyEvidenceRelationReader(),
                documents=self._documents,
                citations=self._citations,
            )
            lineages = collect_document_claim_lineages(
                document_id,
                claims,
                service,
                limits=self._limits,
            )
            return ProofBundleV2Snapshot(source=source, claim_lineages=lineages)


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


def _read_source_snapshot(
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
