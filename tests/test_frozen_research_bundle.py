from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

import tarkka.infrastructure.frozen_research_bundle as frozen_module
from tarkka.application.document_research_state import (
    DocumentResearchState,
    document_research_state_view,
)
from tarkka.application.proof_bundles import (
    ProofBundlePayload,
    ProofBundleSnapshot,
    ProofBundleV2Service,
    ProofBundleV2Snapshot,
    ProofBundleV3Service,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact
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
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.proof_bundle_snapshot import JsonProofBundleV2SnapshotReader
from tests.support.claim_lineage import claim_lineage_fixture, persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_BYTES = b"frozen research fixture"
_SHA256 = hashlib.sha256(_BYTES).hexdigest()
_ARTIFACT_ID = artifact_id_from_sha256(_SHA256)
_DOCUMENT_ID = UUID(int=1)
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


def _source_snapshot() -> ProofBundleSnapshot:
    fixture = claim_lineage_fixture()
    artifact = Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256=_SHA256,
        size_bytes=len(_BYTES),
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", _SHA256),
        original_name="fixture.txt",
        acquired_at=_CREATED_AT,
        source_uri="https://example.test/paper",
    )
    document = replace(fixture.document, artifact_id=_ARTIFACT_ID)
    return ProofBundleSnapshot(document=document, artifact=artifact)


def _empty_snapshot() -> ProofBundleV2Snapshot:
    source = _source_snapshot()
    return ProofBundleV2Snapshot(
        source=source,
        research_state=DocumentResearchState(document_id=_DOCUMENT_ID, claim_lineages=()),
    )


def _v3_payload() -> ProofBundlePayload:
    return ProofBundleV3Service(
        snapshots=_SnapshotReader(_empty_snapshot()),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
        encode_normalized_document=canonical_normalized_document_bytes,
    ).build(_DOCUMENT_ID)


def _v2_payload() -> ProofBundlePayload:
    return ProofBundleV2Service(
        snapshots=_SnapshotReader(_empty_snapshot()),
        artifacts=_ArtifactStore(),  # type: ignore[arg-type]
        encode_research_state=canonical_research_state_bytes,
    ).build(_DOCUMENT_ID)


def _valid_state(home: Path) -> dict[str, object]:
    fixture = persist_local_claim_lineage(home)
    documents = JsonResearchRepository.open_existing(home / "catalog.json")
    assert documents is not None
    snapshot = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations_path=home / "source_observations.json",
        extractions_path=home / "extractions.json",
        verifications_path=home / "verifications.json",
        citations_path=home / "citations.json",
    ).read(fixture.document.document_id)
    assert snapshot is not None
    state = copy.deepcopy(document_research_state_view(snapshot.research_state))
    claims = state["claims"]
    assert isinstance(claims, list)
    for lineage in claims:
        assert isinstance(lineage, dict)
        _rebind_source(lineage["claim_source"])
        evidence = lineage["claim_evidence"]
        assert isinstance(evidence, list)
        for item in evidence:
            _rebind_evidence(item)
        verification = lineage["verification"]
        assert isinstance(verification, dict)
        assessments = verification["assessments"]
        assert isinstance(assessments, list)
        for assessment in assessments:
            assert isinstance(assessment, dict)
            if assessment["evidence"] is not None:
                _rebind_evidence(assessment["evidence"])
    return state


def _rebind_source(value: object) -> None:
    assert isinstance(value, dict)
    document = value["document"]
    artifact = value["artifact"]
    assert isinstance(document, dict)
    assert isinstance(artifact, dict)
    document["artifact_id"] = str(_ARTIFACT_ID)
    artifact.update(
        artifact_id=str(_ARTIFACT_ID),
        sha256=_SHA256,
        size_bytes=len(_BYTES),
        media_type="text/plain",
        source_uri="https://example.test/paper",
    )


def _rebind_evidence(value: object) -> None:
    assert isinstance(value, dict)
    _rebind_source({"document": value["document"], "artifact": value["artifact"]})


def _claims(state: dict[str, object]) -> list[dict[str, object]]:
    values = state["claims"]
    assert isinstance(values, list)
    return values  # type: ignore[return-value]


def _with_state(payload: ProofBundlePayload, state: object) -> ProofBundlePayload:
    state_bytes = canonical_research_state_bytes(state)
    manifest = replace(payload.manifest, research_state=research_state_descriptor(state_bytes))
    return replace(payload, manifest=manifest, research_state_bytes=state_bytes)


def _write_bundle(tmp_path: Path, payload: ProofBundlePayload, name: str = "bundle.tarkka") -> Path:
    path = tmp_path / name
    path.write_bytes(build_proof_bundle_bytes(payload))
    return path


def test_inspection_projects_production_lineage_shapes_and_all_evidence_kinds(
    tmp_path: Path,
) -> None:
    state = _valid_state(tmp_path / "state")
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    frozen = inspect_frozen_research_bundle(path, limits=ProofBundleVerificationLimits())

    assert frozen.document_id == str(_DOCUMENT_ID)
    assert frozen.artifact.artifact_id == str(_ARTIFACT_ID)
    assert frozen.artifact.sha256 == _SHA256
    assert frozen.normalized_document.parser_name == "fixture"
    assert frozen.normalized_document.parser_version == "1"
    assert len(frozen.claims) == 1
    assert len(frozen.claims[0].evidence) == 4
    assert len(frozen.claims[0].verifications) == 1
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


def test_inspection_rejects_incomplete_research_root(tmp_path: Path) -> None:
    state = _valid_state(tmp_path / "state")
    del state["format"]
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    with pytest.raises(FrozenResearchBundleInspectionError, match="unexpected or missing fields"):
        inspect_frozen_research_bundle(path)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("format", "wrong", "unsupported frozen research-state format"),
    ("schema_version", 2, "unsupported frozen research-state schema version"),
    ("claims", {}, "claims must be an array"),
])
def test_inspection_rejects_invalid_research_root_contract(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    state = _valid_state(tmp_path / field)
    state[field] = value
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state), name=f"{field}.tarkka")

    with pytest.raises(FrozenResearchBundleInspectionError, match=message):
        inspect_frozen_research_bundle(path)


def test_bundle_builder_owns_research_document_identity_invariant(tmp_path: Path) -> None:
    state = _valid_state(tmp_path / "state")
    state["document_id"] = str(UUID(int=999))

    with pytest.raises(ProofBundleVerificationError, match="document identity does not match manifest"):
        build_proof_bundle_bytes(_with_state(_v3_payload(), state))


def test_inspection_rejects_incomplete_claim_evidence_and_verification_shapes(tmp_path: Path) -> None:
    cases: list[tuple[str, str]] = [
        ("claim", "Claim has unexpected or missing fields"),
        ("evidence", "Evidence has unexpected or missing fields"),
        ("verification", "verification assessment has unexpected or missing fields"),
    ]
    for index, (kind, message) in enumerate(cases):
        state = _valid_state(tmp_path / f"state-{index}")
        lineage = _claims(state)[0]
        if kind == "claim":
            claim = lineage["claim"]
            assert isinstance(claim, dict)
            del claim["claim_type"]
        elif kind == "evidence":
            evidence = lineage["claim_evidence"]
            assert isinstance(evidence, list)
            assert isinstance(evidence[0], dict)
            del evidence[0]["text"]
        else:
            verification = lineage["verification"]
            assert isinstance(verification, dict)
            assessments = verification["assessments"]
            assert isinstance(assessments, list)
            assert isinstance(assessments[0], dict)
            del assessments[0]["confidence"]
        path = _write_bundle(
            tmp_path,
            _with_state(_v3_payload(), state),
            name=f"incomplete-{index}.tarkka",
        )
        with pytest.raises(FrozenResearchBundleInspectionError, match=message):
            inspect_frozen_research_bundle(path)


def test_inspection_allows_same_evidence_identity_with_identical_content_across_claims(
    tmp_path: Path,
) -> None:
    state = _valid_state(tmp_path / "state")
    first = _claims(state)[0]
    second = copy.deepcopy(first)
    claim = second["claim"]
    assert isinstance(claim, dict)
    claim["claim_id"] = str(UUID(int=800))
    claim["text"] = "A second Claim can cite the same exact Evidence."
    _claims(state).append(second)
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    frozen = inspect_frozen_research_bundle(path)

    assert len(frozen.claims) == 2
    assert frozen.claims[0].evidence == frozen.claims[1].evidence


def test_inspection_rejects_same_evidence_identity_with_conflicting_content(
    tmp_path: Path,
) -> None:
    state = _valid_state(tmp_path / "state")
    second = copy.deepcopy(_claims(state)[0])
    claim = second["claim"]
    evidence = second["claim_evidence"]
    assert isinstance(claim, dict)
    assert isinstance(evidence, list)
    assert isinstance(evidence[0], dict)
    claim["claim_id"] = str(UUID(int=800))
    claim["text"] = "Second Claim"
    evidence[0]["text"] = "omega"
    _claims(state).append(second)
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    with pytest.raises(FrozenResearchBundleInspectionError, match="different content"):
        inspect_frozen_research_bundle(path)


def test_inspection_rejects_relation_identity_reused_across_claims(tmp_path: Path) -> None:
    state = _valid_state(tmp_path / "state")
    second = copy.deepcopy(_claims(state)[0])
    claim = second["claim"]
    assert isinstance(claim, dict)
    claim["claim_id"] = str(UUID(int=800))
    claim["text"] = "Second Claim"
    _claims(state).append(second)
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    with pytest.raises(FrozenResearchBundleInspectionError, match="reuses a verification relation"):
        inspect_frozen_research_bundle(path)


def test_inspection_rejects_incomplete_pages(tmp_path: Path) -> None:
    state = _valid_state(tmp_path / "state")
    lineage = _claims(state)[0]
    page = lineage["claim_evidence_page"]
    assert isinstance(page, dict)
    page["offset"] = 1
    path = _write_bundle(tmp_path, _with_state(_v3_payload(), state))

    with pytest.raises(FrozenResearchBundleInspectionError, match="not a complete frozen view"):
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
