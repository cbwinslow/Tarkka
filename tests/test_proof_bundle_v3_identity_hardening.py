from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.models import Document
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH
from tarkka.infrastructure.normalized_document_json import (
    canonical_normalized_document_bytes,
    normalized_document_descriptor,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    canonical_research_state_bytes,
    research_state_descriptor,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    _zip_info,
    build_proof_bundle_bytes,
    canonical_manifest_bytes,
    verify_proof_bundle_bytes,
)
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

_OTHER_DOCUMENT_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _valid_v3_payload() -> ProofBundlePayload:
    base = proof_bundle_payload()
    document = Document(
        document_id=base.manifest.document.document_id,
        artifact_id=base.manifest.document.artifact_id,
        title=base.manifest.document.title,
        parser_name=base.manifest.document.parser_name,
        parser_version=base.manifest.document.parser_version,
        sections=(),
        normalized_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    state_bytes = canonical_research_state_bytes(
        {
            "document_id": str(document.document_id),
            "claims": [],
        }
    )
    document_bytes = canonical_normalized_document_bytes(document)
    manifest = ProofBundleManifestV3(
        document=base.manifest.document,
        artifact=base.manifest.artifact,
        research_state=research_state_descriptor(state_bytes),
        normalized_document=normalized_document_descriptor(document_bytes),
        work_documents=base.manifest.work_documents,
        source_observations=base.manifest.source_observations,
        resource_links=base.manifest.resource_links,
    )
    return ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=base.artifact_bytes,
        research_state_bytes=state_bytes,
        normalized_document_bytes=document_bytes,
    )


def _archive(payload: ProofBundlePayload) -> bytes:
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.research_state_bytes is not None
    assert payload.normalized_document_bytes is not None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in (
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            (payload.manifest.research_state.path, payload.research_state_bytes),
            (payload.manifest.normalized_document.path, payload.normalized_document_bytes),
        ):
            archive.writestr(_zip_info(name), data)
    return buffer.getvalue()


def test_v3_builder_and_verifier_reject_research_state_for_another_document() -> None:
    payload = _valid_v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.normalized_document_bytes is not None
    wrong_state = canonical_research_state_bytes(
        {"document_id": str(_OTHER_DOCUMENT_ID), "claims": []}
    )
    bad_payload = ProofBundlePayload(
        manifest=replace(
            payload.manifest,
            research_state=research_state_descriptor(wrong_state),
        ),
        artifact_bytes=payload.artifact_bytes,
        research_state_bytes=wrong_state,
        normalized_document_bytes=payload.normalized_document_bytes,
    )

    with pytest.raises(ProofBundleVerificationError, match="research-state document identity"):
        build_proof_bundle_bytes(bad_payload)
    with pytest.raises(ProofBundleVerificationError, match="research-state document identity"):
        verify_proof_bundle_bytes(_archive(bad_payload))


def test_v3_builder_rejects_research_state_without_document_identity() -> None:
    payload = _valid_v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.normalized_document_bytes is not None
    wrong_state = canonical_research_state_bytes([])
    bad_payload = ProofBundlePayload(
        manifest=replace(
            payload.manifest,
            research_state=research_state_descriptor(wrong_state),
        ),
        artifact_bytes=payload.artifact_bytes,
        research_state_bytes=wrong_state,
        normalized_document_bytes=payload.normalized_document_bytes,
    )

    with pytest.raises(ProofBundleVerificationError, match="research-state document identity"):
        build_proof_bundle_bytes(bad_payload)


def test_v3_builder_rejects_normalized_document_identity_mismatch() -> None:
    payload = _valid_v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.research_state_bytes is not None
    assert payload.normalized_document_bytes is not None
    document_value = json.loads(payload.normalized_document_bytes)
    document_value["title"] = "Different title"
    wrong_document = _canonical_json(document_value)
    bad_payload = ProofBundlePayload(
        manifest=replace(
            payload.manifest,
            normalized_document=normalized_document_descriptor(wrong_document),
        ),
        artifact_bytes=payload.artifact_bytes,
        research_state_bytes=payload.research_state_bytes,
        normalized_document_bytes=wrong_document,
    )

    with pytest.raises(ProofBundleVerificationError, match="normalized-document identity"):
        build_proof_bundle_bytes(bad_payload)
