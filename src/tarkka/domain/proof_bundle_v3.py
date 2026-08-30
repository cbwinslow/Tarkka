"""Explicit proof-bundle v3 manifest contract for deterministic Document replay.

Versions 1 and 2 remain frozen. Version 3 reuses all v2 source/research-state semantics and adds
one integrity-bound canonical normalized-Document member.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tarkka.domain.identifiers import require_sha256
from tarkka.domain.proof_bundle_v2 import (
    ProofBundleManifestV2,
    ProofBundleResearchState,
    proof_bundle_manifest_v2_from_dict,
)
from tarkka.domain.proof_bundles import (
    PROOF_BUNDLE_FORMAT,
    ProofBundleArtifact,
    ProofBundleDocument,
    ProofBundleResourceLink,
    ProofBundleSourceObservation,
    ProofBundleWorkDocumentLink,
)

PROOF_BUNDLE_SCHEMA_VERSION_V3 = 3
PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH = "replay/normalized-document.json"


@dataclass(frozen=True, slots=True)
class ProofBundleNormalizedDocument:
    """Integrity descriptor for the canonical deterministic normalized-Document member."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if self.path != PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH:
            raise ValueError(
                "proof bundle normalized-document path must be replay/normalized-document.json"
            )
        require_sha256(self.sha256, field_name="proof bundle normalized-document sha256")
        if self.size_bytes < 0:
            raise ValueError("proof bundle normalized-document size must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class ProofBundleManifestV3:
    """Proof-bundle v3 manifest with research state and deterministic Document replay content."""

    document: ProofBundleDocument
    artifact: ProofBundleArtifact
    research_state: ProofBundleResearchState
    normalized_document: ProofBundleNormalizedDocument
    work_documents: tuple[ProofBundleWorkDocumentLink, ...] = ()
    source_observations: tuple[ProofBundleSourceObservation, ...] = ()
    resource_links: tuple[ProofBundleResourceLink, ...] = ()
    format: str = PROOF_BUNDLE_FORMAT
    schema_version: int = PROOF_BUNDLE_SCHEMA_VERSION_V3

    def __post_init__(self) -> None:
        _v2_manifest(self)
        if self.schema_version != PROOF_BUNDLE_SCHEMA_VERSION_V3:
            raise ValueError(f"unsupported proof bundle schema version: {self.schema_version}")

    def to_dict(self) -> dict[str, object]:
        payload = _v2_manifest(self).to_dict()
        payload["schema_version"] = self.schema_version
        payload["normalized_document"] = self.normalized_document.to_dict()
        return payload


def proof_bundle_manifest_v3_from_dict(value: object) -> ProofBundleManifestV3:
    """Parse the strict v3 manifest while delegating shared fields to the frozen v2 parser."""
    root = _mapping(value, "proof bundle manifest")
    expected = {
        "format",
        "schema_version",
        "document",
        "artifact",
        "work_documents",
        "source_observations",
        "resource_links",
        "research_state",
        "normalized_document",
    }
    if set(root) != expected:
        raise ValueError("proof bundle manifest has unexpected or missing fields")
    schema_version = _integer(root["schema_version"], "proof bundle schema_version")
    if schema_version != PROOF_BUNDLE_SCHEMA_VERSION_V3:
        raise ValueError(f"unsupported proof bundle schema version: {schema_version}")

    base_value = dict(root)
    normalized_value = base_value.pop("normalized_document")
    base_value["schema_version"] = 2
    base = proof_bundle_manifest_v2_from_dict(base_value)

    normalized = _mapping(normalized_value, "proof bundle normalized_document")
    if set(normalized) != {"path", "sha256", "size_bytes"}:
        raise ValueError("proof bundle normalized_document has unexpected or missing fields")
    descriptor = ProofBundleNormalizedDocument(
        path=_string(normalized["path"], "proof bundle normalized-document path"),
        sha256=_string(normalized["sha256"], "proof bundle normalized-document sha256"),
        size_bytes=_integer(
            normalized["size_bytes"],
            "proof bundle normalized-document size_bytes",
        ),
    )
    return ProofBundleManifestV3(
        document=base.document,
        artifact=base.artifact,
        research_state=base.research_state,
        normalized_document=descriptor,
        work_documents=base.work_documents,
        source_observations=base.source_observations,
        resource_links=base.resource_links,
        format=base.format,
        schema_version=schema_version,
    )


def _v2_manifest(manifest: ProofBundleManifestV3) -> ProofBundleManifestV2:
    return ProofBundleManifestV2(
        document=manifest.document,
        artifact=manifest.artifact,
        research_state=manifest.research_state,
        work_documents=manifest.work_documents,
        source_observations=manifest.source_observations,
        resource_links=manifest.resource_links,
        format=manifest.format,
    )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} must be an object with string keys")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value
