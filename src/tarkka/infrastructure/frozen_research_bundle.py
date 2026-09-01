"""Bounded projection of verified schema-v3 proof bundles into frozen research state."""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from tarkka.application.document_research_state import (
    DOCUMENT_RESEARCH_STATE_FORMAT,
    DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION,
)
from tarkka.application.frozen_research_diff import (
    FrozenArtifactState,
    FrozenClaimState,
    FrozenEntityState,
    FrozenNormalizedDocumentState,
    FrozenResearchBundle,
)
from tarkka.application.normalized_document_view import (
    NORMALIZED_DOCUMENT_FORMAT,
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
)
from tarkka.domain.proof_bundle_v3 import PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH
from tarkka.infrastructure.normalized_document_json import (
    NormalizedDocumentJsonError,
    parse_canonical_normalized_document_bytes,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    canonical_research_state_bytes,
    parse_canonical_research_state_bytes,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    verify_proof_bundle,
)

_RESEARCH_STATE_PATH = "research/claim-lineage.json"
_READ_CHUNK_BYTES = 1024 * 1024


class FrozenResearchBundleInspectionError(ProofBundleVerificationError):
    """Raised when verified v3 content cannot be projected into the diff contract."""


def inspect_frozen_research_bundle(
    path: Path,
    *,
    limits: ProofBundleVerificationLimits | None = None,
) -> FrozenResearchBundle:
    """Verify and project one immutable schema-v3 bundle without reading Artifact bytes twice."""
    effective_limits = limits or ProofBundleVerificationLimits()
    try:
        verification = verify_proof_bundle(path, limits=effective_limits)
    except ProofBundleVerificationError as exc:
        raise FrozenResearchBundleInspectionError(str(exc)) from exc
    if verification.member_count != 4:
        raise FrozenResearchBundleInspectionError(
            "frozen research diff requires proof bundle schema version 3"
        )

    try:
        with path.open("rb") as handle:
            _require_verified_digest(handle, verification.bundle_sha256)
            handle.seek(0)
            with zipfile.ZipFile(handle, mode="r") as archive:
                manifest_bytes = _read_bounded_member(
                    archive,
                    PROOF_BUNDLE_MANIFEST_PATH,
                    maximum_size=effective_limits.max_manifest_bytes,
                )
                research_bytes = _read_bounded_member(
                    archive,
                    _RESEARCH_STATE_PATH,
                    maximum_size=effective_limits.max_research_state_bytes,
                )
                document_bytes = _read_bounded_member(
                    archive,
                    PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
                    maximum_size=effective_limits.max_normalized_document_bytes,
                )
            handle.seek(0)
            _require_verified_digest(handle, verification.bundle_sha256)
    except FrozenResearchBundleInspectionError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise FrozenResearchBundleInspectionError(
            f"unable to inspect frozen proof bundle: {path}"
        ) from exc

    try:
        research_value = parse_canonical_research_state_bytes(research_bytes)
        document_value = parse_canonical_normalized_document_bytes(document_bytes)
    except (ProofBundleResearchStateJsonError, NormalizedDocumentJsonError) as exc:
        raise FrozenResearchBundleInspectionError(str(exc)) from exc

    research = _mapping(research_value, "research state")
    document = _mapping(document_value, "normalized document")
    _validate_member_contracts(research, document)
    document_id = _canonical_uuid(document.get("document_id"), "normalized document document_id")
    if document_id != verification.document_id:
        raise FrozenResearchBundleInspectionError(
            "normalized Document identity changed after proof-bundle verification"
        )
    artifact_id = _canonical_uuid(document.get("artifact_id"), "normalized document artifact_id")
    claims = _project_claims(research, expected_document_id=document_id)
    return FrozenResearchBundle(
        bundle_sha256=verification.bundle_sha256,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        document_id=document_id,
        artifact=FrozenArtifactState(
            artifact_id=artifact_id,
            sha256=verification.artifact_sha256,
            size_bytes=verification.artifact_size_bytes,
        ),
        normalized_document=FrozenNormalizedDocumentState(
            document_id=document_id,
            sha256=hashlib.sha256(document_bytes).hexdigest(),
            parser_name=_non_blank_string(document.get("parser_name"), "parser_name"),
            parser_version=_non_blank_string(document.get("parser_version"), "parser_version"),
        ),
        claims=claims,
    )


def _validate_member_contracts(
    research: Mapping[str, Any],
    document: Mapping[str, Any],
) -> None:
    if document.get("format") != NORMALIZED_DOCUMENT_FORMAT:
        raise FrozenResearchBundleInspectionError("unsupported normalized Document format")
    if document.get("schema_version") != NORMALIZED_DOCUMENT_SCHEMA_VERSION:
        raise FrozenResearchBundleInspectionError("unsupported normalized Document schema version")
    if research.get("format") != DOCUMENT_RESEARCH_STATE_FORMAT:
        raise FrozenResearchBundleInspectionError("unsupported frozen research-state format")
    if research.get("schema_version") != DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION:
        raise FrozenResearchBundleInspectionError("unsupported frozen research-state schema version")


def _project_claims(
    research: Mapping[str, Any],
    *,
    expected_document_id: str,
) -> tuple[FrozenClaimState, ...]:
    expected_root = {"format", "schema_version", "document_id", "claims"}
    if set(research) != expected_root:
        raise FrozenResearchBundleInspectionError(
            "frozen research state has unexpected or missing fields"
        )
    research_document_id = _canonical_uuid(research["document_id"], "research-state document_id")
    if research_document_id != expected_document_id:
        raise FrozenResearchBundleInspectionError(
            "research-state Document identity does not match normalized Document"
        )
    claims_value = research["claims"]
    if not isinstance(claims_value, list):
        raise FrozenResearchBundleInspectionError("frozen research-state claims must be an array")

    claims: list[FrozenClaimState] = []
    claim_ids: set[str] = set()
    for raw_claim in claims_value:
        item = _mapping(raw_claim, "Claim lineage")
        expected_keys = {
            "claim",
            "claim_source",
            "claim_evidence_page",
            "claim_evidence",
            "verification",
        }
        if set(item) != expected_keys:
            raise FrozenResearchBundleInspectionError(
                "frozen Claim lineage has unexpected or missing fields"
            )
        claim = _mapping(item["claim"], "Claim")
        claim_id = _canonical_uuid(claim.get("claim_id"), "Claim claim_id")
        claim_document_id = _canonical_uuid(claim.get("document_id"), "Claim document_id")
        if claim_document_id != expected_document_id:
            raise FrozenResearchBundleInspectionError(
                "frozen Claim belongs to a different Document"
            )
        if claim_id in claim_ids:
            raise FrozenResearchBundleInspectionError(
                "frozen research state contains duplicate Claim identities"
            )
        claim_ids.add(claim_id)

        evidence_values = _complete_page(
            item["claim_evidence_page"],
            item["claim_evidence"],
            label="Claim evidence",
        )
        verification = _mapping(item["verification"], "Claim verification")
        assessment_values = _complete_verification_page(verification)
        claims.append(
            FrozenClaimState(
                claim=_fingerprint(
                    claim_id,
                    {"claim": item["claim"], "claim_source": item["claim_source"]},
                ),
                evidence=_project_entities(
                    evidence_values,
                    identity_field="evidence_id",
                    label="Evidence",
                ),
                verifications=_project_entities(
                    assessment_values,
                    identity_field="relation_id",
                    label="verification relation",
                ),
            )
        )
    return tuple(sorted(claims, key=lambda item: item.claim.entity_id))


def _complete_page(page_value: object, values: object, *, label: str) -> list[Any]:
    page = _mapping(page_value, f"{label} page")
    if set(page) != {"offset", "limit", "total"}:
        raise FrozenResearchBundleInspectionError(f"{label} page has unexpected fields")
    items = _list(values, label)
    total = _non_negative_integer(page["total"], f"{label} total")
    offset = _non_negative_integer(page["offset"], f"{label} offset")
    limit = _non_negative_integer(page["limit"], f"{label} limit")
    if offset != 0 or total != len(items) or limit != total:
        raise FrozenResearchBundleInspectionError(f"{label} page is not a complete frozen view")
    return items


def _complete_verification_page(value: Mapping[str, Any]) -> list[Any]:
    if set(value) != {"offset", "limit", "total", "assessments"}:
        raise FrozenResearchBundleInspectionError(
            "Claim verification page has unexpected or missing fields"
        )
    return _complete_page(
        {key: value[key] for key in ("offset", "limit", "total")},
        value["assessments"],
        label="verification assessment",
    )


def _project_entities(
    values: list[Any],
    *,
    identity_field: str,
    label: str,
) -> tuple[FrozenEntityState, ...]:
    projected: list[FrozenEntityState] = []
    identities: set[str] = set()
    for raw in values:
        item = _mapping(raw, label)
        entity_id = _canonical_uuid(item.get(identity_field), f"{label} {identity_field}")
        if entity_id in identities:
            raise FrozenResearchBundleInspectionError(
                f"frozen research state contains duplicate {label} identities"
            )
        identities.add(entity_id)
        projected.append(_fingerprint(entity_id, item))
    return tuple(sorted(projected))


def _fingerprint(entity_id: str, value: object) -> FrozenEntityState:
    return FrozenEntityState(
        entity_id=entity_id,
        sha256=hashlib.sha256(canonical_research_state_bytes(value)).hexdigest(),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrozenResearchBundleInspectionError(f"frozen {label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise FrozenResearchBundleInspectionError(f"frozen {label} must be an array")
    return value


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FrozenResearchBundleInspectionError(f"frozen {label} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise FrozenResearchBundleInspectionError(f"frozen {label} must be a UUID string") from exc
    if str(parsed) != value:
        raise FrozenResearchBundleInspectionError(f"frozen {label} must use canonical UUID spelling")
    return value


def _non_blank_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrozenResearchBundleInspectionError(f"frozen {label} must be a non-blank string")
    return value


def _non_negative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FrozenResearchBundleInspectionError(f"frozen {label} must be a non-negative integer")
    return value


def _read_bounded_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    maximum_size: int,
) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > maximum_size:
        raise FrozenResearchBundleInspectionError(
            f"frozen proof bundle member exceeds configured limit: {name}"
        )
    return archive.read(name)


def _require_verified_digest(handle: BinaryIO, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    try:
        while chunk := handle.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    except OSError as exc:
        raise FrozenResearchBundleInspectionError(
            "unable to hash frozen proof bundle during inspection"
        ) from exc
    if digest.hexdigest() != expected_sha256:
        raise FrozenResearchBundleInspectionError("proof bundle changed after verification")
