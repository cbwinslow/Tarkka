"""Reusable proof-bundle fixtures shared by focused test modules."""

from __future__ import annotations

from uuid import UUID

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.proof_bundles import (
    ProofBundleArtifact,
    ProofBundleDocument,
    ProofBundleManifest,
    ProofBundleResourceLink,
    ProofBundleSourceObservation,
    ProofBundleWorkDocumentLink,
    artifact_member_path,
)

_FIXTURE_BYTES = b"fixture"
_FIXTURE_SHA256 = "f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d"
_FIXTURE_ARTIFACT_ID = artifact_id_from_sha256(_FIXTURE_SHA256)
_FIXTURE_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fe01")
_FIXTURE_WORK_ID = UUID("00000000-0000-0000-0000-00000000fe02")
_FIXTURE_WORK_LINK_ID = UUID("00000000-0000-0000-0000-00000000fe03")
_FIXTURE_OBSERVATION_ID = UUID("00000000-0000-0000-0000-00000000fe04")
_FIXTURE_RESOURCE_LINK_ID = UUID("00000000-0000-0000-0000-00000000fe05")
_FIXTURE_TIME = "2026-08-29T00:00:00+00:00"


def proof_bundle_payload() -> ProofBundlePayload:
    """Return a deterministic valid v1 payload with representative lineage."""
    artifact = ProofBundleArtifact(
        artifact_id=_FIXTURE_ARTIFACT_ID,
        sha256=_FIXTURE_SHA256,
        size_bytes=len(_FIXTURE_BYTES),
        media_type="text/plain",
        path=artifact_member_path(_FIXTURE_SHA256),
        original_name="fixture.txt",
        source_uri="https://example.test/fixture.txt",
        acquired_at=_FIXTURE_TIME,
    )
    document = ProofBundleDocument(
        document_id=_FIXTURE_DOCUMENT_ID,
        artifact_id=_FIXTURE_ARTIFACT_ID,
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        normalized_at=_FIXTURE_TIME,
    )
    work_document = ProofBundleWorkDocumentLink(
        link_id=_FIXTURE_WORK_LINK_ID,
        work_id=_FIXTURE_WORK_ID,
        artifact_id=_FIXTURE_ARTIFACT_ID,
        document_id=_FIXTURE_DOCUMENT_ID,
        linked_at=_FIXTURE_TIME,
    )
    observation = ProofBundleSourceObservation(
        observation_id=_FIXTURE_OBSERVATION_ID,
        source_name="fixture",
        basis="native",
        source_version="1",
        provider_record_id="fixture-1",
        media_type="text/plain",
        native_artifact_id=_FIXTURE_ARTIFACT_ID,
        metadata={"fixture": True},
        observed_at=_FIXTURE_TIME,
    )
    resource_link = ProofBundleResourceLink(
        link_id=_FIXTURE_RESOURCE_LINK_ID,
        observation_id=_FIXTURE_OBSERVATION_ID,
        target_uri="https://example.test/supplement.csv",
        relation="supplement",
        media_type="text/csv",
        label="Supplement",
        metadata={"fixture": True},
    )
    return ProofBundlePayload(
        manifest=ProofBundleManifest(
            document=document,
            artifact=artifact,
            work_documents=(work_document,),
            source_observations=(observation,),
            resource_links=(resource_link,),
        ),
        artifact_bytes=_FIXTURE_BYTES,
    )
