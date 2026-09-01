"""Bounded projection of verified schema-v3 proof bundles into frozen research state."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

from tarkka.application.frozen_research_diff import (
    FrozenArtifactState,
    FrozenNormalizedDocumentState,
    FrozenResearchBundle,
)
from tarkka.domain.proof_bundle_v2 import proof_bundle_manifest_from_versioned_dict
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH
from tarkka.infrastructure.frozen_research_view import (
    FrozenResearchStateProjectionError,
    project_frozen_claims,
)
from tarkka.infrastructure.normalized_document_json import (
    NormalizedDocumentJsonError,
    parse_canonical_normalized_document_bytes,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    parse_canonical_research_state_bytes,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    verify_proof_bundle,
)

_READ_CHUNK_BYTES = 1024 * 1024
_DEFAULT_PUBLIC_DETAIL = "frozen proof bundle inspection failed"
_SCHEMA_V3_PUBLIC_DETAIL = "frozen research diff requires proof bundle schema version 3"


class FrozenResearchBundleInspectionError(ProofBundleVerificationError):
    """Raised when verified v3 content cannot be projected into the diff contract."""

    def __init__(
        self,
        message: str,
        *,
        public_detail: str = _DEFAULT_PUBLIC_DETAIL,
    ) -> None:
        super().__init__(message)
        self.public_detail = public_detail


def inspect_frozen_research_bundle(
    path: Path,
    *,
    limits: ProofBundleVerificationLimits | None = None,
) -> FrozenResearchBundle:
    """Verify and project one immutable schema-v3 bundle without rereading Artifact bytes."""
    effective_limits = limits or ProofBundleVerificationLimits()
    try:
        verification = verify_proof_bundle(path, limits=effective_limits)
    except ProofBundleVerificationError as exc:
        raise FrozenResearchBundleInspectionError(str(exc)) from exc

    try:
        with path.open("rb") as handle:
            _require_verified_digest(handle, verification.bundle_sha256)
            handle.seek(0)
            with zipfile.ZipFile(handle, mode="r") as archive:
                manifest_bytes = _read_bounded_member(
                    archive,
                    PROOF_BUNDLE_MANIFEST_PATH,
                    maximum_size=effective_limits.max_manifest_bytes,
                )
                manifest = proof_bundle_manifest_from_versioned_dict(json.loads(manifest_bytes))
                if not isinstance(manifest, ProofBundleManifestV3):
                    raise FrozenResearchBundleInspectionError(
                        _SCHEMA_V3_PUBLIC_DETAIL,
                        public_detail=_SCHEMA_V3_PUBLIC_DETAIL,
                    )
                research_bytes = _read_bounded_member(
                    archive,
                    manifest.research_state.path,
                    maximum_size=effective_limits.max_research_state_bytes,
                )
                document_bytes = _read_bounded_member(
                    archive,
                    manifest.normalized_document.path,
                    maximum_size=effective_limits.max_normalized_document_bytes,
                )
            handle.seek(0)
            _require_verified_digest(handle, verification.bundle_sha256)
    except FrozenResearchBundleInspectionError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise FrozenResearchBundleInspectionError("unable to inspect frozen proof bundle") from exc

    try:
        research = parse_canonical_research_state_bytes(research_bytes)
        document = parse_canonical_normalized_document_bytes(document_bytes)
        document_id = str(manifest.document.document_id)
        artifact_id = str(manifest.document.artifact_id)
        _require_normalized_identity(document, manifest)
        claims = project_frozen_claims(
            research,
            expected_document_id=document_id,
            expected_artifact_id=artifact_id,
        )
    except (
        ProofBundleResearchStateJsonError,
        NormalizedDocumentJsonError,
        FrozenResearchStateProjectionError,
    ) as exc:
        raise FrozenResearchBundleInspectionError(str(exc)) from exc

    return FrozenResearchBundle(
        bundle_sha256=verification.bundle_sha256,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        document_id=document_id,
        artifact=FrozenArtifactState(
            artifact_id=artifact_id,
            sha256=verification.artifact_sha256,
            size_bytes=verification.artifact_size_bytes,
        ),
        normalized_document=FrozenNormalizedDocumentState(
            document_id=document_id,
            sha256=hashlib.sha256(document_bytes).hexdigest(),
            parser_name=manifest.document.parser_name,
            parser_version=manifest.document.parser_version,
        ),
        claims=claims,
    )


def _require_normalized_identity(
    document: Mapping[str, object],
    manifest: ProofBundleManifestV3,
) -> None:
    expected = {
        "document_id": str(manifest.document.document_id),
        "artifact_id": str(manifest.document.artifact_id),
        "title": manifest.document.title,
        "parser_name": manifest.document.parser_name,
        "parser_version": manifest.document.parser_version,
    }
    if any(document.get(field) != expected_value for field, expected_value in expected.items()):
        raise FrozenResearchStateProjectionError(
            "normalized Document identity changed after proof-bundle verification"
        )


def _read_bounded_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    maximum_size: int,
) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > maximum_size:
        raise FrozenResearchBundleInspectionError(
            f"frozen proof bundle member exceeds configured limit: {name}"
        )
    return archive.read(name)


def _require_verified_digest(handle: BinaryIO, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    try:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    except OSError as exc:
        raise FrozenResearchBundleInspectionError(
            "unable to hash frozen proof bundle during inspection"
        ) from exc
    if digest.hexdigest() != expected_sha256:
        raise FrozenResearchBundleInspectionError("proof bundle changed after verification")
