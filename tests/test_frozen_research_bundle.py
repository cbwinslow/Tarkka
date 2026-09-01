from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

import tarkka.infrastructure.frozen_research_bundle as frozen_module
from tarkka.application.document_research_state import DocumentResearchState
from tarkka.application.proof_bundles import (
    ProofBundlePayload,
    ProofBundleSnapshot,
    ProofBundleV2Service,
    ProofBundleV2Snapshot,
    ProofBundleV3Service,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.frozen_research_bundle import (
    FrozenResearchBundleInspectionError,
    inspect_frozen_research_bundle,
)
from tarkka.infrastructure.normalized_document_json import canonical_normalized_document_bytes
from tarkka.infrastructure.proof_bundle_v2 import (
    canonical_research_state_bytes,
    research_state_descriptor,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    build_proof_bundle_bytes,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_BYTES = b"frozen research fixture"
_SHA256 = hashlib.sha256(_BYTES).hexdigest()
_ARTIFACT_ID = artifact_id_from_sha256(_SHA256)
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000d101")
_CLAIM_A = "00000000-0000-0000-0000-00000000c101"
_CLAIM_B = "00000000-0000-0000-0000-00000000c102"
_EVIDENCE_A = "00000000-0000-0000-0000-00000000e101"
_EVIDENCE_B = "00000000-0000-0000-0000-00000000e102"
_RELATION_A = "00000000-0000-0000-0000-00000000a101"
_CREATED_AT = datetime(2026, 9, 1, tzinfo=UTC)


class _SnapshotReader:
    def __init__(self, snapshot: ProofBundleV2Snapshot) -> None:
        self.snapshot = snapshot

    def read(self, document_id: UUID) -> ProofBundleV2Snapshot | None:
        assert document_id == _DOCUMENT_ID
        return self.snapshot


class _ArtifactStore:
    def read_bytes(self, artifact: Artifact) -> bytes:
        assert artifact.artifact_id == _ARTIFACT_ID
        return _BYTES


def _snapshot() -> ProofBundleV2Snapshot:
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
        title="Frozen fixture",
        parser_name="plain-text",
        parser_version="3",
        sections=(),
        normalized_at=_CREATED_AT,
    )
    return ProofBundleV2Snapshot(
        source=ProofBundleSnapshot(document=document, artifact=artifact),
        research_state=DocumentResearchState(document_id=_DOCUMENT_ID, claim_lineages=()),
    )


def _v3_payload() -> ProofBundlePayload:
    return ProofBundleV3Service(
        snapshots=_SnapshotReader(_snapshot()),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    ).build(_DOCUMENT_ID)


def _v2_payload() -> ProofBundlePayload:
    return ProofBundleV2Service(
        snapshots=_SnapshotReader(_snapshot()),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    ).build(_DOCUMENT_ID)


def _claim(
    claim_id: str,
    *,
    evidence: tuple[str, ...] = (),
    relations: tuple[str, ...] = (),
) -> dict[str, object]:
    evidence_values = [{"evidence_id": identity, "text": identity} for identity in evidence]
    assessments = [{"relation_id": identity, "kind": "supports"} for identity in relations]
    return {
        "claim": {
            "claim_id": claim_id,
            "document_id": str(_DOCUMENT_ID),
            "text": f"Claim {claim_id}",
        },
        "claim_source": {"source": "fixture"},
        "claim_evidence_page": {
            "offset": 0,
            "limit": len(evidence_values),
            "total": len(evidence_values),
        },
        "claim_evidence": evidence_values,
        "verification": {
            "offset": 0,
            "limit": len(assessments),
            "total": len(assessments),
            "assessments": assessments,
        },
    }


def _state(*claims: dict[str, object]) -> dict[str, object]:
    return {
        "format": "tarkka.document-research-state",
        "schema_version": 1,
        "document_id": str(_DOCUMENT_ID),
        "claims": list(claims),
    }


def _with_state(payload: ProofBundlePayload, state: object) -> ProofBundlePayload:
    assert payload.research_state_bytes is not None
    state_bytes = canonical_research_state_bytes(state)
    manifest = replace(payload.manifest, research_state=research_state_descriptor(state_bytes))
    return replace(payload, manifest=manifest, research_state_bytes=state_bytes)


def _write_bundle(tmp_path: Path, payload: ProofBundlePayload, name: str = "bundle.tarkka") -> Path:
    path = tmp_path / name
    path.write_bytes(build_proof_bundle_bytes(payload))
    return path


def test_inspection_projects_sorted_identity_fingerprints_from_verified_v3(tmp_path: Path) -> None:
    state = _state(
        _claim(_CLAIM_B),
        _claim(
            _CLAIM_A,
            evidence=(_EVIDENCE_B, _EVIDENCE_A),
            relations=(_RELATION_A,),
        ),
    )
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    frozen = inspect_frozen_research_bundle(path, limits=ProofBundleVerificationLimits())

    assert frozen.document_id == str(_DOCUMENT_ID)
    assert frozen.artifact.artifact_id == str(_ARTIFACT_ID)
    assert frozen.artifact.sha256 == _SHA256
    assert frozen.normalized_document.parser_name == "plain-text"
    assert frozen.normalized_document.parser_version == "3"
    assert [item.claim.entity_id for item in frozen.claims] == [_CLAIM_A, _CLAIM_B]
    assert [item.entity_id for item in frozen.claims[0].evidence] == [
        _EVIDENCE_A,
        _EVIDENCE_B,
    ]
    assert frozen.claims[0].verifications[0].entity_id == _RELATION_A
    assert len(frozen.manifest_sha256) == 64


def test_inspection_rejects_older_bundle_schema(tmp_path: Path) -> None:
    path = _write_bundle(tmp_path, _v2_payload())

    with pytest.raises(FrozenResearchBundleInspectionError, match="schema version 3"):
        inspect_frozen_research_bundle(path)


def test_inspection_normalizes_underlying_verification_failure(tmp_path: Path) -> None:
    path = tmp_path / "broken.tarkka"
    path.write_bytes(b"not a zip")

    with pytest.raises(FrozenResearchBundleInspectionError, match="valid ZIP") as captured:
        inspect_frozen_research_bundle(path)

    assert isinstance(captured.value.__cause__, ProofBundleVerificationError)


def test_inspection_detects_bundle_change_after_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_bundle(tmp_path, _v3_payload())
    verification = frozen_module.verify_proof_bundle(path)
    monkeypatch.setattr(
        frozen_module,
        "verify_proof_bundle",
        lambda *_args, **_kwargs: replace(verification, bundle_sha256="0" * 64),
    )

    with pytest.raises(FrozenResearchBundleInspectionError, match="changed after verification"):
        inspect_frozen_research_bundle(path)


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (
            {"document_id": str(_DOCUMENT_ID), "claims": []},
            "unexpected or missing fields",
        ),
        (
            {**_state(), "format": "wrong"},
            "unsupported frozen research-state format",
        ),
        (
            {**_state(), "schema_version": 2},
            "unsupported frozen research-state schema version",
        ),
        (
            {**_state(), "document_id": "00000000-0000-0000-0000-00000000d999"},
            "does not match normalized Document",
        ),
        (
            {**_state(), "claims": {}},
            "claims must be an array",
        ),
        (
            _state({"claim": {}}),
            "Claim lineage has unexpected or missing fields",
        ),
        (
            _state(
                {
                    **_claim(_CLAIM_A),
                    "claim": {"claim_id": _CLAIM_A, "document_id": str(UUID(int=999))},
                }
            ),
            "Claim belongs to a different Document",
        ),
        (
            _state(_claim(_CLAIM_A), _claim(_CLAIM_A)),
            "duplicate Claim identities",
        ),
        (
            _state(
                {
                    **_claim(_CLAIM_A),
                    "claim_evidence_page": {"offset": 1, "limit": 0, "total": 0},
                }
            ),
            "Claim evidence page is not a complete frozen view",
        ),
        (
            _state(
                {
                    **_claim(_CLAIM_A),
                    "verification": {"offset": 0, "limit": 0, "total": 0},
                }
            ),
            "Claim verification page has unexpected or missing fields",
        ),
        (
            _state(_claim(_CLAIM_A, evidence=(_EVIDENCE_A, _EVIDENCE_A))),
            "duplicate Evidence identities",
        ),
        (
            _state(_claim(_CLAIM_A, relations=(_RELATION_A, _RELATION_A))),
            "duplicate verification relation identities",
        ),
    ],
)
def test_inspection_rejects_semantically_invalid_but_canonical_research_state(
    tmp_path: Path,
    state: object,
    message: str,
) -> None:
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    with pytest.raises(FrozenResearchBundleInspectionError, match=message):
        inspect_frozen_research_bundle(path)


def test_inspection_rejects_noncanonical_research_identity_fields(tmp_path: Path) -> None:
    invalid_states = (
        _state({**_claim(_CLAIM_A), "claim": {"claim_id": 1, "document_id": str(_DOCUMENT_ID)}}),
        _state(
            {
                **_claim(_CLAIM_A),
                "claim": {"claim_id": "not-a-uuid", "document_id": str(_DOCUMENT_ID)},
            }
        ),
        _state(
            {
                **_claim(_CLAIM_A),
                "claim": {"claim_id": "{00000000-0000-0000-0000-00000000c101}", "document_id": str(_DOCUMENT_ID)},
            }
        ),
    )
    messages = ("UUID string", "UUID string", "canonical UUID spelling")

    for index, (state, message) in enumerate(zip(invalid_states, messages, strict=True)):
        path = _write_bundle(
            tmp_path,
            _with_state(_v3_payload(), state),
            name=f"invalid-{index}.tarkka",
        )
        with pytest.raises(FrozenResearchBundleInspectionError, match=message):
            inspect_frozen_research_bundle(path)


def test_inspection_rejects_invalid_page_scalar_types(tmp_path: Path) -> None:
    claim = _claim(_CLAIM_A)
    claim["claim_evidence_page"] = {"offset": 0, "limit": False, "total": 0}
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), _state(claim)))

    with pytest.raises(FrozenResearchBundleInspectionError, match="non-negative integer"):
        inspect_frozen_research_bundle(path)


def test_inspection_rejects_non_array_evidence(tmp_path: Path) -> None:
    claim = _claim(_CLAIM_A)
    claim["claim_evidence"] = {}
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), _state(claim)))

    with pytest.raises(FrozenResearchBundleInspectionError, match="must be an array"):
        inspect_frozen_research_bundle(path)


def test_inspection_rejects_non_object_nested_entity(tmp_path: Path) -> None:
    claim = _claim(_CLAIM_A)
    claim["claim_evidence_page"] = {"offset": 0, "limit": 1, "total": 1}
    claim["claim_evidence"] = ["not-an-object"]
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), _state(claim)))

    with pytest.raises(FrozenResearchBundleInspectionError, match="Evidence must be an object"):
        inspect_frozen_research_bundle(path)


def test_inspection_propagates_invalid_limit_configuration(tmp_path: Path) -> None:
    path = _write_bundle(tmp_path, _v3_payload())

    with pytest.raises(ValueError, match="verification limits must be positive"):
        inspect_frozen_research_bundle(
            path,
            limits=ProofBundleVerificationLimits(max_archive_bytes=0),
        )


def test_inspection_can_translate_post_verify_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_bundle(tmp_path, _v3_payload())
    verification = frozen_module.verify_proof_bundle(path)
    monkeypatch.setattr(
        frozen_module,
        "verify_proof_bundle",
        lambda *_args, **_kwargs: verification,
    )
    path.unlink()

    with pytest.raises(FrozenResearchBundleInspectionError, match="unable to inspect"):
        inspect_frozen_research_bundle(path)
