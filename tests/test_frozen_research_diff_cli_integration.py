from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.document_research_state import DocumentResearchState
from tarkka.application.proof_bundles import (
    ProofBundlePayload,
    ProofBundleSnapshot,
    ProofBundleV2Snapshot,
    ProofBundleV3Service,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.normalized_document_json import canonical_normalized_document_bytes
from tarkka.infrastructure.proof_bundle_v2 import (
    canonical_research_state_bytes,
    research_state_descriptor,
)
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes
from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.integration, pytest.mark.regression]

_BYTES = b"Frozen diff integration fixture."
_SHA256 = hashlib.sha256(_BYTES).hexdigest()
_ARTIFACT_ID = artifact_id_from_sha256(_SHA256)
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000d301")
_CLAIM_ID = "00000000-0000-0000-0000-00000000c301"
_EVIDENCE_ID = "00000000-0000-0000-0000-00000000e301"
_CREATED_AT = datetime(2026, 9, 1, tzinfo=UTC)


class _SnapshotReader:
    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None:
        assert document_id == _DOCUMENT_ID
        artifact = Artifact(
            artifact_id=_ARTIFACT_ID,
            sha256=_SHA256,
            size_bytes=len(_BYTES),
            media_type="text/plain",
            storage_key=PurePosixPath("sha256", _SHA256),
            original_name="fixture.txt",
            acquired_at=_CREATED_AT,
            source_uri=None,
        )
        document = Document(
            document_id=_DOCUMENT_ID,
            artifact_id=_ARTIFACT_ID,
            title="Frozen diff fixture",
            parser_name="plain-text",
            parser_version="3",
            sections=(),
            normalized_at=_CREATED_AT,
        )
        return ProofBundleV2Snapshot(
            source=ProofBundleSnapshot(document=document, artifact=artifact),
            research_state=DocumentResearchState(document_id=_DOCUMENT_ID, claim_lineages=()),
        )


class _ArtifactStore:
    def read_bytes(self, artifact: Artifact) -> bytes:
        assert artifact.artifact_id == _ARTIFACT_ID
        return _BYTES


def _payload() -> ProofBundlePayload:
    return ProofBundleV3Service(
        snapshots=_SnapshotReader(),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    ).build(_DOCUMENT_ID)


def _payload_with_claim() -> ProofBundlePayload:
    payload = _payload()
    state = {
        "format": "tarkka.document-research-state",
        "schema_version": 1,
        "document_id": str(_DOCUMENT_ID),
        "claims": [
            {
                "claim": {
                    "claim_id": _CLAIM_ID,
                    "document_id": str(_DOCUMENT_ID),
                    "text": "The fixture supports a deterministic diff.",
                },
                "claim_source": {"source": "fixture"},
                "claim_evidence_page": {"offset": 0, "limit": 1, "total": 1},
                "claim_evidence": [
                    {
                        "evidence_id": _EVIDENCE_ID,
                        "text": "Frozen diff integration fixture.",
                    }
                ],
                "verification": {
                    "offset": 0,
                    "limit": 0,
                    "total": 0,
                    "assessments": [],
                },
            }
        ],
    }
    state_bytes = canonical_research_state_bytes(state)
    return replace(
        payload,
        manifest=replace(payload.manifest, research_state=research_state_descriptor(state_bytes)),
        research_state_bytes=state_bytes,
    )


def _write(path: Path, payload: ProofBundlePayload) -> None:
    path.write_bytes(build_proof_bundle_bytes(payload))


def test_public_diff_cli_compares_real_verified_v3_bundles_offline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = tmp_path / "before.tarkka"
    equal = tmp_path / "equal.tarkka"
    changed = tmp_path / "changed.tarkka"
    payload = _payload()
    _write(before, payload)
    _write(equal, payload)
    _write(changed, _payload_with_claim())

    assert main(["diff", str(before), str(equal)]) == 0
    equal_result = json.loads(capsys.readouterr().out)
    assert equal_result["materially_equal"] is True
    assert equal_result["claims"] == []

    assert main(["diff", str(before), str(changed)]) == 1
    changed_result = json.loads(capsys.readouterr().out)
    assert changed_result["materially_equal"] is False
    assert changed_result["claims"][0]["claim_id"] == _CLAIM_ID
    assert changed_result["claims"][0]["change"] == "added"
    assert changed_result["claims"][0]["evidence"]["added"][0]["id"] == _EVIDENCE_ID
