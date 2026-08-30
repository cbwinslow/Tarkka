"""Explicit proof-bundle v2 manifest contracts.

Version 1 remains frozen in :mod:`tarkka.domain.proof_bundles`. Version 2 adds only a
descriptor for one canonical research-state member while reusing all v1 source/document
lineage models and invariants.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tarkka.domain.identifiers import require_sha256
from tarkka.domain.proof_bundles import (
    PROOF_BUNDLE_FORMAT,
    ProofBundleArtifact,
    ProofBundleDocument,
    ProofBundleManifest,
    ProofBundleResourceLink,
    ProofBundleSourceObservation,
    ProofBundleWorkDocumentLink,
    proof_bundle_manifest_from_dict,
)

if TYPE_CHECKING:
    from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3

PROOF_BUNDLE_SCHEMA_VERSION_V2 = 2
PROOF_BUNDLE_RESEARCH_STATE_PATH = "research/claim-lineage.json"


@dataclass(frozen=True, slots=True)
class ProofBundleResearchState:
    """Integrity descriptor for the canonical v2 research-state JSON member."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if self.path != PROOF_BUNDLE_RESEARCH_STATE_PATH:
            raise ValueError(
                "proof bundle research-state path must be research/claim-lineage.json"
            )
        require_sha256(self.sha256, field_name="proof bundle research-state sha256")
        if self.size_bytes < 0:
            raise ValueError("proof bundle research-state size must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class ProofBundleManifestV2:
    """Proof-bundle v2 manifest with one integrity-bound research-state member."""

    document: ProofBundleDocument
    artifact: ProofBundleArtifact
    research_state: ProofBundleResearchState
    work_documents: tuple[ProofBundleWorkDocumentLink, ...] = ()
    source_observations: tuple[ProofBundleSourceObservation, ...] = ()
    resource_links: tuple[ProofBundleResourceLink, ...] = ()
    format: str = PROOF_BUNDLE_FORMAT
    schema_version: int = PROOF_BUNDLE_SCHEMA_VERSION_V2

    def __post_init__(self) -> None:
        _v1_manifest(self)
        if self.schema_version != PROOF_BUNDLE_SCHEMA_VERSION_V2:
            raise ValueError(f"unsupported proof bundle schema version: {self.schema_version}")

    def to_dict(self) -> dict[str, object]:
        payload = _v1_manifest(self).to_dict()
        payload["schema_version"] = self.schema_version
        payload["research_state"] = self.research_state.to_dict()
        return payload


def proof_bundle_manifest_v2_from_dict(value: object) -> ProofBundleManifestV2:
    """Parse the strict v2 manifest while delegating shared v1 fields to the frozen v1 parser."""
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
    }
    if set(root) != expected:
        raise ValueError("proof bundle manifest has unexpected or missing fields")
    schema_version = _integer(root["schema_version"], "proof bundle schema_version")
    if schema_version != PROOF_BUNDLE_SCHEMA_VERSION_V2:
        raise ValueError(f"unsupported proof bundle schema version: {schema_version}")

    base_value = dict(root)
    research_value = base_value.pop("research_state")
    base_value["schema_version"] = 1
    base = proof_bundle_manifest_from_dict(base_value)

    research = _mapping(research_value, "proof bundle research_state")
    if set(research) != {"path", "sha256", "size_bytes"}:
        raise ValueError("proof bundle research_state has unexpected or missing fields")
    descriptor = ProofBundleResearchState(
        path=_string(research["path"], "proof bundle research-state path"),
        sha256=_string(research["sha256"], "proof bundle research-state sha256"),
        size_bytes=_integer(
            research["size_bytes"],
            "proof bundle research-state size_bytes",
        ),
    )
    return ProofBundleManifestV2(
        document=base.document,
        artifact=base.artifact,
        research_state=descriptor,
        work_documents=base.work_documents,
        source_observations=base.source_observations,
        resource_links=base.resource_links,
        format=base.format,
        schema_version=schema_version,
    )


def proof_bundle_manifest_from_versioned_dict(
    value: object,
) -> ProofBundleManifest | ProofBundleManifestV2 | ProofBundleManifestV3:
    """Dispatch untrusted manifest data to frozen v1/v2 parsers or explicit newer versions."""
    if isinstance(value, Mapping):
        schema_version = value.get("schema_version")
        if schema_version == PROOF_BUNDLE_SCHEMA_VERSION_V2:
            return proof_bundle_manifest_v2_from_dict(value)
        if schema_version == 3:
            return _proof_bundle_manifest_v3_or_frozen(value)
    return proof_bundle_manifest_from_dict(value)


def _proof_bundle_manifest_v3_or_frozen(
    value: Mapping[str, Any],
) -> ProofBundleManifest | ProofBundleManifestV3:
    """Parse a structurally v3 manifest or preserve the frozen older-version rejection path."""
    # A version number alone must never reinterpret an older manifest shape. The v3 parser is
    # selected only when its defining member descriptor is present; otherwise the frozen v1
    # parser rejects the unsupported version as it always has.
    if "normalized_document" not in value:
        return proof_bundle_manifest_from_dict(value)

    from tarkka.domain.proof_bundle_v3 import proof_bundle_manifest_v3_from_dict

    return proof_bundle_manifest_v3_from_dict(value)


def _v1_manifest(manifest: ProofBundleManifestV2) -> ProofBundleManifest:
    return ProofBundleManifest(
        document=manifest.document,
        artifact=manifest.artifact,
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
