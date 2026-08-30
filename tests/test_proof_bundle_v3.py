from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.models import Document
from tarkka.domain.proof_bundle_v2 import (
    ProofBundleManifestV2,
    proof_bundle_manifest_from_versioned_dict,
)
from tarkka.domain.proof_bundle_v3 import (
    PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
    PROOF_BUNDLE_SCHEMA_VERSION_V3,
    ProofBundleManifestV3,
    ProofBundleNormalizedDocument,
    proof_bundle_manifest_v3_from_dict,
)
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH
from tarkka.infrastructure.normalized_document_json import (
    NormalizedDocumentJsonError,
    canonical_normalized_document_bytes,
    normalized_document_descriptor,
    parse_canonical_normalized_document_bytes,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    canonical_research_state_bytes,
    research_state_descriptor,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    _zip_info,
    build_proof_bundle_bytes,
    canonical_manifest_bytes,
    verify_proof_bundle_bytes,
)
from tests.support.claim_lineage import claim_lineage_fixture
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


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


def _archive(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members:
            archive.writestr(_zip_info(name), data)
    return buffer.getvalue()


def _manifest_document() -> Document:
    base = proof_bundle_payload().manifest
    return Document(
        document_id=base.document.document_id,
        artifact_id=base.document.artifact_id,
        title=base.document.title,
        parser_name=base.document.parser_name,
        parser_version=base.document.parser_version,
        sections=(),
        normalized_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def _v3_payload() -> ProofBundlePayload:
    base = proof_bundle_payload()
    state_bytes = canonical_research_state_bytes(
        {
            "format": "tarkka-document-research-state",
            "schema_version": 1,
            "document_id": str(base.manifest.document.document_id),
            "claims": [],
        }
    )
    document_bytes = canonical_normalized_document_bytes(_manifest_document())
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


def _v3_archive(payload: ProofBundlePayload, *, document_bytes: bytes | None = None) -> bytes:
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.research_state_bytes is not None
    assert payload.normalized_document_bytes is not None
    return _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            (payload.manifest.research_state.path, payload.research_state_bytes),
            (
                payload.manifest.normalized_document.path,
                payload.normalized_document_bytes if document_bytes is None else document_bytes,
            ),
        ]
    )


def test_v3_manifest_archive_and_version_dispatch_round_trip_deterministically() -> None:
    payload = _v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)

    parsed = proof_bundle_manifest_v3_from_dict(payload.manifest.to_dict())
    dispatched = proof_bundle_manifest_from_versioned_dict(payload.manifest.to_dict())
    first = build_proof_bundle_bytes(payload)
    second = build_proof_bundle_bytes(payload)
    verification = verify_proof_bundle_bytes(first)

    assert parsed == payload.manifest
    assert dispatched == payload.manifest
    assert first == second
    assert verification.member_count == 4
    with zipfile.ZipFile(io.BytesIO(first), "r") as archive:
        assert archive.namelist() == [
            PROOF_BUNDLE_MANIFEST_PATH,
            payload.manifest.artifact.path,
            payload.manifest.research_state.path,
            PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
        ]
        assert (
            archive.read(PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH)
            == payload.normalized_document_bytes
        )


def test_v3_payload_requires_and_integrity_binds_both_added_members() -> None:
    payload = _v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.research_state_bytes is not None
    assert payload.normalized_document_bytes is not None

    with pytest.raises(ValueError, match="v3 requires"):
        ProofBundlePayload(
            manifest=payload.manifest,
            artifact_bytes=payload.artifact_bytes,
            research_state_bytes=payload.research_state_bytes,
        )
    with pytest.raises(ValueError, match="research-state bytes do not match"):
        ProofBundlePayload(
            manifest=payload.manifest,
            artifact_bytes=payload.artifact_bytes,
            research_state_bytes=b"{}\n",
            normalized_document_bytes=payload.normalized_document_bytes,
        )
    with pytest.raises(ValueError, match="normalized-document bytes do not match"):
        ProofBundlePayload(
            manifest=payload.manifest,
            artifact_bytes=payload.artifact_bytes,
            research_state_bytes=payload.research_state_bytes,
            normalized_document_bytes=b"{}\n",
        )


def test_v2_payload_rejects_v3_replay_bytes() -> None:
    v3 = _v3_payload()
    assert isinstance(v3.manifest, ProofBundleManifestV3)
    v2 = ProofBundleManifestV2(
        document=v3.manifest.document,
        artifact=v3.manifest.artifact,
        research_state=v3.manifest.research_state,
        work_documents=v3.manifest.work_documents,
        source_observations=v3.manifest.source_observations,
        resource_links=v3.manifest.resource_links,
    )
    assert v3.research_state_bytes is not None
    assert v3.normalized_document_bytes is not None

    with pytest.raises(ValueError, match="v2 must not carry normalized-document"):
        ProofBundlePayload(
            manifest=v2,
            artifact_bytes=v3.artifact_bytes,
            research_state_bytes=v3.research_state_bytes,
            normalized_document_bytes=v3.normalized_document_bytes,
        )


def test_v3_descriptor_and_manifest_constructors_reject_invalid_invariants() -> None:
    descriptor = normalized_document_descriptor(
        canonical_normalized_document_bytes(_manifest_document())
    )
    with pytest.raises(ValueError, match="path must be"):
        replace(descriptor, path="replay/other.json")
    with pytest.raises(ValueError, match="sha256"):
        replace(descriptor, sha256="not-a-digest")
    with pytest.raises(ValueError, match="size must be non-negative"):
        replace(descriptor, size_bytes=-1)

    manifest = _v3_payload().manifest
    assert isinstance(manifest, ProofBundleManifestV3)
    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        replace(manifest, schema_version=4)


def test_v3_manifest_parser_rejects_invalid_shapes_and_descriptor_types() -> None:
    valid = cast(dict[str, Any], _v3_payload().manifest.to_dict())

    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_v3_from_dict([])

    missing = dict(valid)
    missing.pop("normalized_document")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_v3_from_dict(missing)

    for bad_version in (4, True):
        invalid = dict(valid, schema_version=bad_version)
        pattern = "must be an integer" if bad_version is True else "unsupported"
        with pytest.raises(ValueError, match=pattern):
            proof_bundle_manifest_v3_from_dict(invalid)

    invalid_descriptor = dict(valid, normalized_document=[])
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_v3_from_dict(invalid_descriptor)

    extra = json.loads(json.dumps(valid))
    extra["normalized_document"]["extra"] = True
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_v3_from_dict(extra)

    bad_path = json.loads(json.dumps(valid))
    bad_path["normalized_document"]["path"] = 3
    with pytest.raises(ValueError, match="must be a string"):
        proof_bundle_manifest_v3_from_dict(bad_path)

    bad_size = json.loads(json.dumps(valid))
    bad_size["normalized_document"]["size_bytes"] = False
    with pytest.raises(ValueError, match="must be an integer"):
        proof_bundle_manifest_v3_from_dict(bad_size)


def test_normalized_document_json_is_canonical_strict_and_timestamp_independent() -> None:
    fixture = claim_lineage_fixture()
    first = canonical_normalized_document_bytes(fixture.document)
    later = canonical_normalized_document_bytes(
        replace(
            fixture.document,
            normalized_at=fixture.document.normalized_at.replace(year=2027),
        )
    )
    parsed = parse_canonical_normalized_document_bytes(first)
    descriptor = normalized_document_descriptor(first)

    assert first == later
    assert parsed["document_id"] == str(fixture.document.document_id)
    assert parsed["sections"]
    assert parsed["figures"]
    assert parsed["tables"]
    assert parsed["equations"]
    assert "normalized_at" not in parsed
    assert descriptor.sha256 == hashlib.sha256(first).hexdigest()
    assert descriptor.size_bytes == len(first)

    with pytest.raises(NormalizedDocumentJsonError, match="not JSON-compatible"):
        canonical_normalized_document_bytes(replace(fixture.document, title="\ud800"))
    with pytest.raises(NormalizedDocumentJsonError, match="not valid UTF-8"):
        parse_canonical_normalized_document_bytes(b"\xff")
    with pytest.raises(NormalizedDocumentJsonError, match="not valid JSON"):
        parse_canonical_normalized_document_bytes(b"{\n")
    with pytest.raises(NormalizedDocumentJsonError, match="not canonically encoded"):
        parse_canonical_normalized_document_bytes(first.replace(b'"title":', b'"title" :', 1))
    with pytest.raises(NormalizedDocumentJsonError, match="duplicate JSON key"):
        parse_canonical_normalized_document_bytes(b'{"a":1,"a":2}\n')
    with pytest.raises(NormalizedDocumentJsonError, match="non-finite number"):
        parse_canonical_normalized_document_bytes(b'{"a":NaN}\n')


def test_verifier_rejects_v3_member_integrity_limit_and_identity_mismatches() -> None:
    payload = _v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.normalized_document_bytes is not None
    value = cast(dict[str, Any], payload.manifest.to_dict())

    missing_member = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            (payload.manifest.research_state.path, cast(bytes, payload.research_state_bytes)),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="missing, unexpected, or noncanonical"):
        verify_proof_bundle_bytes(missing_member)

    wrong_size = json.loads(json.dumps(value))
    wrong_size["normalized_document"]["size_bytes"] += 1
    wrong_size_archive = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, _canonical_json(wrong_size)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            (payload.manifest.research_state.path, cast(bytes, payload.research_state_bytes)),
            (payload.manifest.normalized_document.path, payload.normalized_document_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="byte length does not match"):
        verify_proof_bundle_bytes(wrong_size_archive)

    wrong_digest = json.loads(json.dumps(value))
    wrong_digest["normalized_document"]["sha256"] = "0" * 64
    wrong_digest_archive = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, _canonical_json(wrong_digest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            (payload.manifest.research_state.path, cast(bytes, payload.research_state_bytes)),
            (payload.manifest.normalized_document.path, payload.normalized_document_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="sha256 does not match"):
        verify_proof_bundle_bytes(wrong_digest_archive)

    data = build_proof_bundle_bytes(payload)
    with pytest.raises(ProofBundleVerificationError, match="normalized-document member exceeds"):
        verify_proof_bundle_bytes(
            data,
            limits=ProofBundleVerificationLimits(
                max_archive_bytes=len(data),
                max_manifest_bytes=len(canonical_manifest_bytes(payload.manifest)),
                max_artifact_bytes=len(payload.artifact_bytes),
                max_research_state_bytes=len(cast(bytes, payload.research_state_bytes)),
                max_normalized_document_bytes=len(payload.normalized_document_bytes) - 1,
            ),
        )

    document_value = json.loads(payload.normalized_document_bytes)
    document_value["title"] = "Different title"
    mismatched = _canonical_json(document_value)
    mismatched_manifest = replace(
        payload.manifest,
        normalized_document=ProofBundleNormalizedDocument(
            path=PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
            sha256=hashlib.sha256(mismatched).hexdigest(),
            size_bytes=len(mismatched),
        ),
    )
    mismatch_archive = _archive(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(mismatched_manifest)),
            (mismatched_manifest.artifact.path, payload.artifact_bytes),
            (mismatched_manifest.research_state.path, cast(bytes, payload.research_state_bytes)),
            (mismatched_manifest.normalized_document.path, mismatched),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="identity does not match"):
        verify_proof_bundle_bytes(mismatch_archive)


def test_verifier_rejects_noncanonical_v3_replay_json_and_more_than_four_members() -> None:
    payload = _v3_payload()
    assert isinstance(payload.manifest, ProofBundleManifestV3)
    assert payload.normalized_document_bytes is not None
    noncanonical = payload.normalized_document_bytes.replace(b'"title":', b'"title" :', 1)
    manifest = replace(
        payload.manifest,
        normalized_document=ProofBundleNormalizedDocument(
            path=PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
            sha256=hashlib.sha256(noncanonical).hexdigest(),
            size_bytes=len(noncanonical),
        ),
    )
    with pytest.raises(ProofBundleVerificationError, match="not canonically encoded"):
        verify_proof_bundle_bytes(
            _archive(
                [
                    (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(manifest)),
                    (manifest.artifact.path, payload.artifact_bytes),
                    (manifest.research_state.path, cast(bytes, payload.research_state_bytes)),
                    (manifest.normalized_document.path, noncanonical),
                ]
            )
        )

    with pytest.raises(ProofBundleVerificationError, match="unexpected archive members"):
        verify_proof_bundle_bytes(
            _archive(
                [
                    (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
                    (payload.manifest.artifact.path, payload.artifact_bytes),
                    (payload.manifest.research_state.path, cast(bytes, payload.research_state_bytes)),
                    (
                        payload.manifest.normalized_document.path,
                        payload.normalized_document_bytes,
                    ),
                    ("unexpected.txt", b"unexpected"),
                ]
            )
        )

    with pytest.raises(ValueError, match="limits must be positive"):
        verify_proof_bundle_bytes(
            b"",
            limits=ProofBundleVerificationLimits(max_normalized_document_bytes=0),
        )
