"""Path-free publication and verification of retained proof-bundle archives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.models import Artifact
from tarkka.domain.proof_bundle_v3 import PROOF_BUNDLE_SCHEMA_VERSION_V3, ProofBundleManifestV3
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerification,
    ProofBundleVerificationError,
    build_proof_bundle_bytes,
    verify_proof_bundle_bytes,
)
from tarkka.ports.artifacts import ArtifactStore

_HANDLE_PREFIX = "bundle:sha256:"
_BUNDLE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_MEDIA_TYPE = "application/vnd.tarkka.proof-bundle+zip"


class ProofBundleExportConfigurationError(RuntimeError):
    """Raised when an injected archive store contradicts immutable bundle identity."""


class ProofBundleHandleError(ValueError):
    """Raised when a caller supplies a malformed portable bundle handle."""


class RetainedProofBundleNotFoundError(LookupError):
    """Raised when an otherwise valid bundle handle has no retained archive."""


class RetainedProofBundleVerificationError(ValueError):
    """Raised when retained archive bytes do not pass bounded proof-bundle verification."""


class ProofBundleV3Builder(Protocol):
    """Build one replay-ready v3 payload from a persisted Document."""

    def build(self, document_id: UUID) -> ProofBundlePayload: ...


@dataclass(frozen=True, slots=True)
class ProofBundleExportReceipt:
    """Compact receipt for an immutable retained proof-bundle derivative."""

    handle: str
    schema_version: int
    byte_count: int
    document_id: str
    artifact_sha256: str
    verification: ProofBundleVerification

    def to_dict(self) -> dict[str, object]:
        return {
            "handle": self.handle,
            "schema_version": self.schema_version,
            "byte_count": self.byte_count,
            "document_id": self.document_id,
            "artifact_sha256": self.artifact_sha256,
            "verification": self.verification.to_dict(),
        }


def proof_bundle_handle(sha256: str) -> str:
    """Return the stable external handle for archive bytes with this digest."""
    if not isinstance(sha256, str) or _BUNDLE_SHA256.fullmatch(sha256) is None:
        raise ProofBundleHandleError("bundle SHA-256 must be 64 lowercase hexadecimal characters")
    return f"{_HANDLE_PREFIX}{sha256}"


def parse_proof_bundle_handle(value: object) -> str:
    """Validate a bundle handle without touching a storage backend."""
    if not isinstance(value, str) or not value.startswith(_HANDLE_PREFIX):
        raise ProofBundleHandleError(
            "bundle_handle must be bundle:sha256:<64-lowercase-hex>"
        )
    return proof_bundle_handle(value.removeprefix(_HANDLE_PREFIX)).removeprefix(_HANDLE_PREFIX)


class ProofBundleExportService:
    """Publish deterministic v3 archives and verify only retained immutable bytes."""

    def __init__(self, *, bundles: ProofBundleV3Builder, archives: ArtifactStore) -> None:
        self._bundles = bundles
        self._archives = archives

    def export(self, document_id: UUID) -> ProofBundleExportReceipt:
        """Build, verify, retain, then re-verify a portable archive for one Document."""
        payload = self._bundles.build(document_id)
        if not isinstance(payload.manifest, ProofBundleManifestV3):
            raise ProofBundleExportConfigurationError("proof-bundle export requires a v3 runtime")
        if payload.manifest.document.document_id != document_id:
            raise ProofBundleExportConfigurationError(
                "proof-bundle export builder returned a different Document identity"
            )
        archive = build_proof_bundle_bytes(payload)
        verification = verify_proof_bundle_bytes(archive)
        retained = self._archives.put_bytes(
            archive,
            original_name=f"{document_id}.tarkka",
            media_type=_BUNDLE_MEDIA_TYPE,
        )
        self._validate_retained_artifact(
            retained,
            verification,
            byte_count=len(archive),
        )
        retained_verification = self._verify_digest(verification.bundle_sha256)
        return self._receipt(retained_verification, byte_count=len(archive))

    def verify(self, bundle_handle: object) -> ProofBundleVerification:
        """Verify an already-retained archive; never rebuild from canonical state."""
        return self._verify_digest(parse_proof_bundle_handle(bundle_handle))

    def _verify_digest(self, sha256: str) -> ProofBundleVerification:
        try:
            archive = self._archives.read_bytes_by_sha256(sha256)
        except FileNotFoundError as exc:
            raise RetainedProofBundleNotFoundError(
                f"proof bundle not found: {proof_bundle_handle(sha256)}"
            ) from exc
        if len(archive) == 0:
            raise RetainedProofBundleVerificationError("retained proof bundle is empty")
        try:
            verification = verify_proof_bundle_bytes(archive)
        except ProofBundleVerificationError as exc:
            raise RetainedProofBundleVerificationError(str(exc)) from exc
        if verification.bundle_sha256 != sha256:
            raise RetainedProofBundleVerificationError(
                "retained proof bundle bytes do not match the requested handle"
            )
        return verification

    @staticmethod
    def _validate_retained_artifact(
        retained: Artifact,
        verification: ProofBundleVerification,
        *,
        byte_count: int,
    ) -> None:
        if (
            retained.sha256 != verification.bundle_sha256
            or retained.size_bytes != byte_count
            or retained.media_type != _BUNDLE_MEDIA_TYPE
        ):
            raise ProofBundleExportConfigurationError(
                "proof-bundle archive store returned inconsistent immutable metadata"
            )

    @staticmethod
    def _receipt(
        verification: ProofBundleVerification, *, byte_count: int
    ) -> ProofBundleExportReceipt:
        return ProofBundleExportReceipt(
            handle=proof_bundle_handle(verification.bundle_sha256),
            schema_version=PROOF_BUNDLE_SCHEMA_VERSION_V3,
            byte_count=byte_count,
            document_id=verification.document_id,
            artifact_sha256=verification.artifact_sha256,
            verification=verification,
        )
