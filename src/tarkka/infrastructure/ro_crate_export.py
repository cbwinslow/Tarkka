"""RO-Crate export: an additive, read/export-only view of proof-bundle Artifact and Document scope.

This mirrors native proof-bundle v1 scope only (Artifact + Document). Claim/Evidence/citation
lineage is intentionally out of scope here -- see docs/BUNDLE_INTEROPERABILITY.md for the full
design rationale, the five open questions it resolves, and what is deliberately deferred to a
follow-up. This module never replaces, weakens, or changes the native `.tarkka` bundle format,
`tarkka bundle verify`, or `tarkka replay`; it is a second, non-canonical representation of the
same already-verified Artifact and Document identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tarkka.domain.proof_bundle_v2 import ProofBundleManifestV2
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.domain.proof_bundles import ProofBundleManifest

RO_CRATE_SPEC_VERSION = "1.2"
RO_CRATE_CONFORMS_TO = f"https://w3id.org/ro/crate/{RO_CRATE_SPEC_VERSION}"
RO_CRATE_CONTEXT_URL = f"{RO_CRATE_CONFORMS_TO}/context"
_METADATA_FILENAME = "ro-crate-metadata.json"

# Inline, not a hosted URL: this project has no stable public domain to publish a resolvable
# JSON-LD context document at yet. A broken context URL is worse than none. See
# docs/BUNDLE_INTEROPERABILITY.md section 4 for the explicit follow-up this leaves open.
_TARKKA_CONTEXT = {
    "tarkka": (
        "https://github.com/cbwinslow/Tarkka/blob/main/"
        "docs/BUNDLE_INTEROPERABILITY.md#tarkka-context-v1"
    ),
    "TarkkaNormalizedDocument": "tarkka:TarkkaNormalizedDocument",
    "documentId": "tarkka:documentId",
    "parserName": "tarkka:parserName",
    "parserVersion": "tarkka:parserVersion",
    "normalizedAt": "tarkka:normalizedAt",
}

_AnyManifest = ProofBundleManifest | ProofBundleManifestV2 | ProofBundleManifestV3


def artifact_crate_path(sha256: str) -> str:
    """Return the content-addressed relative file path used inside an emitted RO-Crate directory."""
    return f"files/{sha256}"


def build_ro_crate_metadata(manifest: _AnyManifest) -> dict[str, object]:
    """Build a v1-bundle-equivalent (Artifact + Document only) RO-Crate metadata graph.

    The manifest is assumed already verified (see
    ``tarkka.infrastructure.proof_bundles.read_verified_proof_bundle``); this function performs no
    integrity checking and never alters the Artifact SHA-256 or Document identity it is given.
    """
    artifact = manifest.artifact
    document = manifest.document
    artifact_path = artifact_crate_path(artifact.sha256)
    document_id = f"#document-{document.document_id}"

    file_entity: dict[str, object] = {
        "@id": artifact_path,
        "@type": "File",
        "sha256": artifact.sha256,
        "contentSize": str(artifact.size_bytes),
        "encodingFormat": artifact.media_type,
    }
    if artifact.original_name is not None:
        file_entity["name"] = artifact.original_name
    if artifact.source_uri is not None:
        file_entity["url"] = artifact.source_uri

    document_entity: dict[str, object] = {
        "@id": document_id,
        "@type": ["CreativeWork", "TarkkaNormalizedDocument"],
        "name": document.title,
        "isBasedOn": {"@id": artifact_path},
        "documentId": str(document.document_id),
        "parserName": document.parser_name,
        "parserVersion": document.parser_version,
        "normalizedAt": document.normalized_at,
    }

    root_dataset: dict[str, object] = {
        "@id": "./",
        "@type": "Dataset",
        "conformsTo": {"@id": RO_CRATE_CONFORMS_TO},
        "hasPart": [{"@id": artifact_path}],
        "mainEntity": {"@id": document_id},
    }

    metadata_descriptor: dict[str, object] = {
        "@id": _METADATA_FILENAME,
        "@type": "CreativeWork",
        "conformsTo": {"@id": RO_CRATE_CONFORMS_TO},
        "about": {"@id": "./"},
    }

    return {
        "@context": [RO_CRATE_CONTEXT_URL, _TARKKA_CONTEXT],
        "@graph": [metadata_descriptor, root_dataset, file_entity, document_entity],
    }


@dataclass(frozen=True, slots=True)
class RoCrateExportResult:
    output_directory: Path
    metadata_path: Path
    artifact_path: Path


def write_ro_crate(
    output_directory: Path,
    manifest: _AnyManifest,
    artifact_bytes: bytes,
) -> RoCrateExportResult:
    """Write an RO-Crate directory: ro-crate-metadata.json plus the content-addressed artifact file.

    ``artifact_bytes`` must already be verified against ``manifest.artifact.sha256`` (see
    ``read_verified_proof_bundle``) -- this function performs no integrity checking of its own.
    Not canonically encoded/deterministic like the native bundle format: this is a read/export
    representation, not a re-verifiable archive.
    """
    metadata = build_ro_crate_metadata(manifest)
    artifact_path = output_directory / artifact_crate_path(manifest.artifact.sha256)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(artifact_bytes)

    metadata_path = output_directory / _METADATA_FILENAME
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return RoCrateExportResult(
        output_directory=output_directory,
        metadata_path=metadata_path,
        artifact_path=artifact_path,
    )
