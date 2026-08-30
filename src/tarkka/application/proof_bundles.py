"""Build portable proof-bundle payloads from one consistent canonical-state snapshot."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from tarkka.application.document_research_state import (
    DocumentResearchState,
    document_research_state_view,
)
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundle_v2 import (
    PROOF_BUNDLE_RESEARCH_STATE_PATH,
    ProofBundleManifestV2,
    ProofBundleResearchState,
)
from tarkka.domain.proof_bundle_v3 import (
    PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
    ProofBundleManifestV3,
    ProofBundleNormalizedDocument,
)
from tarkka.domain.proof_bundles import (
    ProofBundleArtifact,
    ProofBundleDocument,
    ProofBundleManifest,
    ProofBundleResourceLink,
    ProofBundleSourceObservation,
    ProofBundleWorkDocumentLink,
    artifact_member_path,
)
from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.ports.artifacts import ArtifactStore


class ProofBundleDocumentNotFoundError(LookupError):
    """Raised when a bundle is requested for an unknown normalized Document."""


class ProofBundleArtifactNotFoundError(LookupError):
    """Raised when a Document references an Artifact missing from canonical state."""


class ProofBundleArtifactIntegrityError(RuntimeError):
    """Raised when preserved Artifact bytes do not match their immutable identity."""


class ProofBundleResearchStateIntegrityError(RuntimeError):
    """Raised when v2+ research state contradicts its source Document snapshot."""


@dataclass(frozen=True, slots=True)
class ProofBundleSnapshot:
    """One self-consistent read of the canonical state needed by bundle v1."""

    document: Document
    artifact: Artifact
    work_documents: tuple[WorkDocumentLink, ...] = ()
    source_observations: tuple[SourceObservation, ...] = ()
    resource_links: tuple[ResourceLinkObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class ProofBundleV2Snapshot:
    """One coherent source snapshot plus its complete validated document research state."""

    source: ProofBundleSnapshot
    research_state: DocumentResearchState


class ProofBundleSnapshotReader(Protocol):
    """Backend-specific consistent-read boundary used by proof-bundle v1 creation."""

    def read(self, document_id: UUID) -> ProofBundleSnapshot | None: ...


class ProofBundleV2SnapshotReader(Protocol):
    """Backend-specific coherent read boundary used by proof-bundle v2+ creation."""

    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None: ...


ResearchStateEncoder = Callable[[object], bytes]
NormalizedDocumentEncoder = Callable[[Document], bytes]


@dataclass(frozen=True, slots=True)
class ProofBundlePayload:
    """Validated manifest plus the exact immutable bytes embedded in a proof bundle."""

    manifest: ProofBundleManifest | ProofBundleManifestV2 | ProofBundleManifestV3
    artifact_bytes: bytes
    research_state_bytes: bytes | None = None
    normalized_document_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if isinstance(self.manifest, ProofBundleManifestV3):
            if self.research_state_bytes is None or self.normalized_document_bytes is None:
                raise ValueError(
                    "proof bundle v3 requires research-state and normalized-document bytes"
                )
            _validate_member_bytes(
                self.research_state_bytes,
                sha256=self.manifest.research_state.sha256,
                size_bytes=self.manifest.research_state.size_bytes,
                label="research-state",
            )
            _validate_member_bytes(
                self.normalized_document_bytes,
                sha256=self.manifest.normalized_document.sha256,
                size_bytes=self.manifest.normalized_document.size_bytes,
                label="normalized-document",
            )
        elif isinstance(self.manifest, ProofBundleManifestV2):
            if self.research_state_bytes is None:
                raise ValueError("proof bundle v2 requires research-state bytes")
            if self.normalized_document_bytes is not None:
                raise ValueError("proof bundle v2 must not carry normalized-document bytes")
            _validate_member_bytes(
                self.research_state_bytes,
                sha256=self.manifest.research_state.sha256,
                size_bytes=self.manifest.research_state.size_bytes,
                label="research-state",
            )
        elif self.research_state_bytes is not None or self.normalized_document_bytes is not None:
            raise ValueError("proof bundle v1 must not carry research-state or replay bytes")


class ProofBundleService:
    """Compose a v1 export payload without introducing new canonical research identities."""

    def __init__(self, *, snapshots: ProofBundleSnapshotReader, artifacts: ArtifactStore) -> None:
        self._snapshots = snapshots
        self._artifacts = artifacts

    def build(self, document_id: UUID) -> ProofBundlePayload:
        snapshot = self._snapshots.read(document_id)
        if snapshot is None:
            raise ProofBundleDocumentNotFoundError(f"document not found: {document_id}")
        artifact_bytes = _validated_artifact_bytes(
            snapshot,
            document_id=document_id,
            artifacts=self._artifacts,
        )
        return ProofBundlePayload(
            manifest=_source_manifest(snapshot),
            artifact_bytes=artifact_bytes,
        )


class ProofBundleV2Service:
    """Compose a deterministic v2 payload from one coherent research-state snapshot."""

    def __init__(
        self,
        *,
        snapshots: ProofBundleV2SnapshotReader,
        artifacts: ArtifactStore,
        encode_research_state: ResearchStateEncoder,
    ) -> None:
        self._snapshots = snapshots
        self._artifacts = artifacts
        self._encode_research_state = encode_research_state

    def build(self, document_id: UUID) -> ProofBundlePayload:
        snapshot = self._snapshots.read(document_id)
        if snapshot is None:
            raise ProofBundleDocumentNotFoundError(f"document not found: {document_id}")
        source = snapshot.source
        artifact_bytes = _validated_artifact_bytes(
            source,
            document_id=document_id,
            artifacts=self._artifacts,
        )
        _validate_research_state_identity(snapshot)
        research_state_bytes = self._encode_research_state(
            document_research_state_view(snapshot.research_state)
        )
        research_state = _research_state_descriptor(research_state_bytes)
        base = _source_manifest(source)
        manifest = ProofBundleManifestV2(
            document=base.document,
            artifact=base.artifact,
            research_state=research_state,
            work_documents=base.work_documents,
            source_observations=base.source_observations,
            resource_links=base.resource_links,
        )
        return ProofBundlePayload(
            manifest=manifest,
            artifact_bytes=artifact_bytes,
            research_state_bytes=research_state_bytes,
        )


class ProofBundleV3Service:
    """Compose v3 with the same coherent state plus deterministic normalized Document content."""

    def __init__(
        self,
        *,
        snapshots: ProofBundleV2SnapshotReader,
        artifacts: ArtifactStore,
        encode_research_state: ResearchStateEncoder,
        encode_normalized_document: NormalizedDocumentEncoder,
    ) -> None:
        self._snapshots = snapshots
        self._artifacts = artifacts
        self._encode_research_state = encode_research_state
        self._encode_normalized_document = encode_normalized_document

    def build(self, document_id: UUID) -> ProofBundlePayload:
        snapshot = self._snapshots.read(document_id)
        if snapshot is None:
            raise ProofBundleDocumentNotFoundError(f"document not found: {document_id}")
        source = snapshot.source
        artifact_bytes = _validated_artifact_bytes(
            source,
            document_id=document_id,
            artifacts=self._artifacts,
        )
        _validate_research_state_identity(snapshot)
        research_state_bytes = self._encode_research_state(
            document_research_state_view(snapshot.research_state)
        )
        normalized_document_bytes = self._encode_normalized_document(source.document)
        base = _source_manifest(source)
        manifest = ProofBundleManifestV3(
            document=base.document,
            artifact=base.artifact,
            research_state=_research_state_descriptor(research_state_bytes),
            normalized_document=ProofBundleNormalizedDocument(
                path=PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
                sha256=hashlib.sha256(normalized_document_bytes).hexdigest(),
                size_bytes=len(normalized_document_bytes),
            ),
            work_documents=base.work_documents,
            source_observations=base.source_observations,
            resource_links=base.resource_links,
        )
        return ProofBundlePayload(
            manifest=manifest,
            artifact_bytes=artifact_bytes,
            research_state_bytes=research_state_bytes,
            normalized_document_bytes=normalized_document_bytes,
        )


def _validate_member_bytes(
    data: bytes,
    *,
    sha256: str,
    size_bytes: int,
    label: str,
) -> None:
    if len(data) != size_bytes or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"proof bundle {label} bytes do not match manifest")


def _validate_research_state_identity(snapshot: ProofBundleV2Snapshot) -> None:
    if snapshot.research_state.document_id != snapshot.source.document.document_id:
        raise ProofBundleResearchStateIntegrityError(
            "proof bundle research state belongs to a different Document"
        )


def _research_state_descriptor(data: bytes) -> ProofBundleResearchState:
    return ProofBundleResearchState(
        path=PROOF_BUNDLE_RESEARCH_STATE_PATH,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _validated_artifact_bytes(
    snapshot: ProofBundleSnapshot,
    *,
    document_id: UUID,
    artifacts: ArtifactStore,
) -> bytes:
    document = snapshot.document
    artifact = snapshot.artifact
    if document.document_id != document_id:
        raise ProofBundleArtifactIntegrityError(
            "snapshot returned a different document identity"
        )
    if document.artifact_id != artifact.artifact_id:
        raise ProofBundleArtifactIntegrityError(
            "snapshot document and artifact identities do not match"
        )

    artifact_bytes = artifacts.read_bytes(artifact)
    actual_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    if len(artifact_bytes) != artifact.size_bytes or actual_sha256 != artifact.sha256:
        raise ProofBundleArtifactIntegrityError(
            f"artifact bytes do not match immutable identity: {artifact.artifact_id}"
        )
    return artifact_bytes


def _source_manifest(snapshot: ProofBundleSnapshot) -> ProofBundleManifest:
    document = snapshot.document
    artifact = snapshot.artifact
    return ProofBundleManifest(
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
            for link in sorted(snapshot.work_documents, key=lambda item: str(item.link_id))
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
                snapshot.source_observations,
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
            for link in sorted(snapshot.resource_links, key=lambda item: str(item.link_id))
        ),
    )
