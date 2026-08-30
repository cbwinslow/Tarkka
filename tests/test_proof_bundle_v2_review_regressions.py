from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.proof_bundle_v2 import (
    PROOF_BUNDLE_RESEARCH_STATE_PATH,
    ProofBundleManifestV2,
    ProofBundleResearchState,
)
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH
from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    validate_canonical_research_state_bytes,
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


def _payload_with_state(state_bytes: bytes) -> ProofBundlePayload:
    base = proof_bundle_payload()
    descriptor = ProofBundleResearchState(
        path=PROOF_BUNDLE_RESEARCH_STATE_PATH,
        sha256=hashlib.sha256(state_bytes).hexdigest(),
        size_bytes=len(state_bytes),
    )
    manifest = ProofBundleManifestV2(
        document=base.manifest.document,
        artifact=base.manifest.artifact,
        research_state=descriptor,
        work_documents=base.manifest.work_documents,
        source_observations=base.manifest.source_observations,
        resource_links=base.manifest.resource_links,
    )
    return ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=base.artifact_bytes,
        research_state_bytes=state_bytes,
    )


def _raw_archive(payload: ProofBundlePayload) -> bytes:
    assert isinstance(payload.manifest, ProofBundleManifestV2)
    assert payload.research_state_bytes is not None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            _zip_info(PROOF_BUNDLE_MANIFEST_PATH),
            canonical_manifest_bytes(payload.manifest),
        )
        archive.writestr(
            _zip_info(payload.manifest.artifact.path),
            payload.artifact_bytes,
        )
        archive.writestr(
            _zip_info(payload.manifest.research_state.path),
            payload.research_state_bytes,
        )
    return buffer.getvalue()


def test_builder_rejects_noncanonical_research_state_before_zip_construction() -> None:
    payload = _payload_with_state(b'{"claims": []}\n')

    with pytest.raises(ProofBundleResearchStateJsonError, match="not canonically encoded"):
        build_proof_bundle_bytes(payload)


def test_lone_surrogate_is_translated_by_json_helper_and_archive_verifier() -> None:
    state_bytes = b'{"value":"\\ud800"}\n'
    payload = _payload_with_state(state_bytes)

    with pytest.raises(ProofBundleResearchStateJsonError, match="not JSON-compatible"):
        validate_canonical_research_state_bytes(state_bytes)

    with pytest.raises(ProofBundleVerificationError, match="not JSON-compatible"):
        verify_proof_bundle_bytes(_raw_archive(payload))
