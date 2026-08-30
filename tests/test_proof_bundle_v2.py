from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from typing import Any, cast

import pytest

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.proof_bundle_v2 import (
    PROOF_BUNDLE_RESEARCH_STATE_PATH,
    PROOF_BUNDLE_SCHEMA_VERSION_V2,
    ProofBundleManifestV2,
    ProofBundleResearchState,
    proof_bundle_manifest_from_versioned_dict,
    proof_bundle_manifest_v2_from_dict,
)
from tarkka.domain.proof_bundles import (
    PROOF_BUNDLE_MANIFEST_PATH,
    proof_bundle_manifest_from_dict,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    canonical_research_state_bytes,
    research_state_descriptor,
    validate_canonical_research_state_bytes,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    _zip_info,
    build_proof_bundle_bytes,
    canonical_manifest_bytes,
    verify_proof_bundle_bytes,
)
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def _v2_payload(value: object | None = None) -> ProofBundlePayload:
    base = proof_bundle_payload()
    state_bytes = canonical_research_state_bytes(
        {"claims": []} if value is None else value
    )
    manifest = ProofBundleManifestV2(
        document=base.manifest.document,
        artifact=base.manifest.artifact,
        research_state=research_state_descriptor(state_bytes),
        work_documents=base.manifest.work_documents,
        source_observations=base.manifest.source_observations,
        resource_links=base.manifest.resource_links,
    )
    return ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=base.artifact_bytes,
        research_state_bytes=state_bytes,
    )


def _archive(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members:
            archive.writestr(_zip_info(name), data)
    return buffer.getvalue()


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


def test_v1_contract_remains_frozen_and_version_dispatch_preserves_it() -> None:
    payload = proof_bundle_payload()
    data = build_proof_bundle_bytes(payload)

    with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
        assert archive.namelist() == [
            PROOF_BUNDLE_MANIFEST_PATH,
            payload.manifest.artifact.path,
        ]

    version_two = payload.manifest.to_dict()
    version_two["schema_version"] = PROOF_BUNDLE_SCHEMA_VERSION_V2
    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        proof_bundle_manifest_from_dict(version_two)

    assert proof_bundle_manifest_from_versioned_dict(payload.manifest.to_dict()) == payload.manifest


def test_v2_manifest_and_archive_round_trip_deterministically() -> None:
    payload = _v2_payload({"claims": [{"claim_id": "claim:fixture"}]})
    assert isinstance(payload.manifest, ProofBundleManifestV2)

    parsed = proof_bundle_manifest_v2_from_dict(payload.manifest.to_dict())
    dispatched = proof_bundle_manifest_from_versioned_dict(payload.manifest.to_dict())
    first = build_proof_bundle_bytes(payload)
    second = build_proof_bundle_bytes(payload)
    verification = verify_proof_bundle_bytes(first)

    assert parsed == payload.manifest
    assert dispatched == payload.manifest
    assert canonical_manifest_bytes(parsed) == canonical_manifest_bytes(payload.manifest)
    assert first == second
    assert verification.member_count == 3
    with zipfile.ZipFile(io.BytesIO(first), "r") as archive:
        assert archive.namelist() == [
            PROOF_BUNDLE_MANIFEST_PATH,
            payload.manifest.artifact.path,
            PROOF_BUNDLE_RESEARCH_STATE_PATH,
        ]
        assert archive.read(PROOF_BUNDLE_RESEARCH_STATE_PATH) == payload.research_state_bytes


def test_payload_fails_closed_for_version_and_research_state_mismatches() -> None:
    v1 = proof_bundle_payload()
    with pytest.raises(ValueError, match="v1 must not carry"):
        ProofBundlePayload(
            manifest=v1.manifest,
            artifact_bytes=v1.artifact_bytes,
            research_state_bytes=b"{}\n",
        )

    v2 = _v2_payload()
    assert isinstance(v2.manifest, ProofBundleManifestV2)
    with pytest.raises(ValueError, match="v2 requires"):
        ProofBundlePayload(manifest=v2.manifest, artifact_bytes=v2.artifact_bytes)
    with pytest.raises(ValueError, match="do not match manifest"):
        ProofBundlePayload(
            manifest=v2.manifest,
            artifact_bytes=v2.artifact_bytes,
            research_state_bytes=b'{"claims":[1]}\n',
        )


def test_v2_descriptor_and_manifest_constructor_validate_invariants() -> None:
    valid = research_state_descriptor(canonical_research_state_bytes({"claims": []}))

    with pytest.raises(ValueError, match="path must be"):
        ProofBundleResearchState(path="research/other.json", sha256=valid.sha256, size_bytes=1)
    with pytest.raises(ValueError, match="sha256"):
        ProofBundleResearchState(
            path=PROOF_BUNDLE_RESEARCH_STATE_PATH,
            sha256="not-a-digest",
            size_bytes=1,
        )
    with pytest.raises(ValueError, match="size must be non-negative"):
        ProofBundleResearchState(
            path=PROOF_BUNDLE_RESEARCH_STATE_PATH,
            sha256=valid.sha256,
            size_bytes=-1,
        )

    manifest = _v2_payload().manifest
    assert isinstance(manifest, ProofBundleManifestV2)
    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        replace(manifest, schema_version=3)


def test_v2_manifest_parser_rejects_invalid_shapes_and_descriptor_types() -> None:
    valid = cast(dict[str, Any], _v2_payload().manifest.to_dict())

    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_v2_from_dict([])

    missing = dict(valid)
    missing.pop("research_state")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_v2_from_dict(missing)

    bad_version = dict(valid, schema_version=3)
    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        proof_bundle_manifest_v2_from_dict(bad_version)

    bool_version = dict(valid, schema_version=True)
    with pytest.raises(ValueError, match="must be an integer"):
        proof_bundle_manifest_v2_from_dict(bool_version)

    not_object = dict(valid, research_state=[])
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_v2_from_dict(not_object)

    extra = json.loads(json.dumps(valid))
    extra["research_state"]["extra"] = True
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_v2_from_dict(extra)

    bad_path = json.loads(json.dumps(valid))
    bad_path["research_state"]["path"] = 7
    with pytest.raises(ValueError, match="must be a string"):
        proof_bundle_manifest_v2_from_dict(bad_path)

    bad_size = json.loads(json.dumps(valid))
    bad_size["research_state"]["size_bytes"] = False
    with pytest.raises(ValueError, match="must be an integer"):
        proof_bundle_manifest_v2_from_dict(bad_size)


def test_research_state_json_helpers_enforce_canonical_safe_json() -> None:
    canonical = canonical_research_state_bytes({"b": 1, "a": [True]})
    assert canonical == b'{"a":[true],"b":1}\n'
    validate_canonical_research_state_bytes(canonical)
    descriptor = research_state_descriptor(canonical)
    assert descriptor.path == PROOF_BUNDLE_RESEARCH_STATE_PATH
    assert descriptor.sha256 == hashlib.sha256(canonical).hexdigest()
    assert descriptor.size_bytes == len(canonical)

    with pytest.raises(ProofBundleResearchStateJsonError, match="not JSON-compatible"):
        canonical_research_state_bytes(object())
    with pytest.raises(ProofBundleResearchStateJsonError, match="not JSON-compatible"):
        canonical_research_state_bytes({"bad": float("nan")})
    with pytest.raises(ProofBundleResearchStateJsonError, match="not valid UTF-8"):
        validate_canonical_research_state_bytes(b"\xff")
    with pytest.raises(ProofBundleResearchStateJsonError, match="not valid JSON"):
        validate_canonical_research_state_bytes(b"{\n")
    with pytest.raises(ProofBundleResearchStateJsonError, match="not canonically encoded"):
        validate_canonical_research_state_bytes(b'{ "a":1}\n')
    with pytest.raises(ProofBundleResearchStateJsonError, match="duplicate JSON key"):
        validate_canonical_research_state_bytes(b'{"a":1,"a":2}\n')
    with pytest.raises(ProofBundleResearchStateJsonError, match="non-finite number: NaN"):
        validate_canonical_research_state_bytes(b'{"a":NaN}\n')


def test_verifier_rejects_v1_v2_member_and_version_mismatches() -> None:
    v2 = _v2_payload()
    assert isinstance(v2.manifest, ProofBundleManifestV2)
    assert v2.research_state_bytes is not None

    missing_v2_member = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(v2.manifest)),
            (v2.manifest.artifact.path, v2.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="missing, unexpected, or noncanonical"):
        verify_proof_bundle_bytes(missing_v2_member)

    v1 = proof_bundle_payload()
    extra_v1_member = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(v1.manifest)),
            (v1.manifest.artifact.path, v1.artifact_bytes),
            (PROOF_BUNDLE_RESEARCH_STATE_PATH, b"{}\n"),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="missing, unexpected, or noncanonical"):
        verify_proof_bundle_bytes(extra_v1_member)

    unknown = v1.manifest.to_dict()
    unknown["schema_version"] = 3
    unknown_version = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, _canonical_json(unknown)),
            (v1.manifest.artifact.path, v1.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="unsupported proof bundle schema version"):
        verify_proof_bundle_bytes(unknown_version)

    missing_descriptor = v1.manifest.to_dict()
    missing_descriptor["schema_version"] = PROOF_BUNDLE_SCHEMA_VERSION_V2
    bad_v2_manifest = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, _canonical_json(missing_descriptor)),
            (v1.manifest.artifact.path, v1.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="unexpected or missing fields"):
        verify_proof_bundle_bytes(bad_v2_manifest)


def test_verifier_rejects_v2_research_state_size_digest_limit_and_json_tampering() -> None:
    payload = _v2_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV2)
    assert payload.research_state_bytes is not None
    state_bytes = payload.research_state_bytes
    value = cast(dict[str, Any], payload.manifest.to_dict())

    wrong_size = json.loads(json.dumps(value))
    wrong_size["research_state"]["size_bytes"] = len(state_bytes) + 1
    with pytest.raises(ProofBundleVerificationError, match="byte length does not match"):
        verify_proof_bundle_bytes(
            _archive(
                [
                    (PROOF_BUNDLE_MANIFEST_PATH, _canonical_json(wrong_size)),
                    (payload.manifest.artifact.path, payload.artifact_bytes),
                    (PROOF_BUNDLE_RESEARCH_STATE_PATH, state_bytes),
                ]
            )
        )

    wrong_digest = json.loads(json.dumps(value))
    wrong_digest["research_state"]["sha256"] = "0" * 64
    with pytest.raises(ProofBundleVerificationError, match="sha256 does not match"):
        verify_proof_bundle_bytes(
            _archive(
                [
                    (PROOF_BUNDLE_MANIFEST_PATH, _canonical_json(wrong_digest)),
                    (payload.manifest.artifact.path, payload.artifact_bytes),
                    (PROOF_BUNDLE_RESEARCH_STATE_PATH, state_bytes),
                ]
            )
        )

    data = build_proof_bundle_bytes(payload)
    with pytest.raises(ProofBundleVerificationError, match="research-state member exceeds"):
        verify_proof_bundle_bytes(
            data,
            limits=ProofBundleVerificationLimits(
                max_archive_bytes=len(data),
                max_manifest_bytes=len(canonical_manifest_bytes(payload.manifest)),
                max_artifact_bytes=len(payload.artifact_bytes),
                max_research_state_bytes=len(state_bytes) - 1,
            ),
        )

    noncanonical = b'{"claims": []}\n'
    descriptor = ProofBundleResearchState(
        path=PROOF_BUNDLE_RESEARCH_STATE_PATH,
        sha256=hashlib.sha256(noncanonical).hexdigest(),
        size_bytes=len(noncanonical),
    )
    noncanonical_payload = ProofBundlePayload(
        manifest=replace(payload.manifest, research_state=descriptor),
        artifact_bytes=payload.artifact_bytes,
        research_state_bytes=noncanonical,
    )
    with pytest.raises(ProofBundleVerificationError, match="not canonically encoded"):
        verify_proof_bundle_bytes(build_proof_bundle_bytes(noncanonical_payload))

    duplicate = b'{"claims":[],"claims":[]}\n'
    duplicate_descriptor = ProofBundleResearchState(
        path=PROOF_BUNDLE_RESEARCH_STATE_PATH,
        sha256=hashlib.sha256(duplicate).hexdigest(),
        size_bytes=len(duplicate),
    )
    duplicate_payload = ProofBundlePayload(
        manifest=replace(payload.manifest, research_state=duplicate_descriptor),
        artifact_bytes=payload.artifact_bytes,
        research_state_bytes=duplicate,
    )
    with pytest.raises(ProofBundleVerificationError, match="duplicate JSON key"):
        verify_proof_bundle_bytes(build_proof_bundle_bytes(duplicate_payload))


def test_verifier_rejects_more_than_three_members_and_nonpositive_v2_limit() -> None:
    payload = _v2_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV2)
    assert payload.research_state_bytes is not None

    data = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            (PROOF_BUNDLE_RESEARCH_STATE_PATH, payload.research_state_bytes),
            ("unexpected.txt", b"unexpected"),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="unexpected archive members"):
        verify_proof_bundle_bytes(data)

    with pytest.raises(ValueError, match="limits must be positive"):
        verify_proof_bundle_bytes(
            b"",
            limits=ProofBundleVerificationLimits(max_research_state_bytes=0),
        )
