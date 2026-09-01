"""Deterministic comparison model for two already-verified frozen research states."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class FrozenEntityState:
    """Canonical fingerprint for one identity-addressed frozen research entity."""

    entity_id: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.entity_id, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class FrozenClaimState:
    """One Claim plus the Evidence and verification relations frozen beneath it."""

    claim: FrozenEntityState
    evidence: tuple[FrozenEntityState, ...]
    verifications: tuple[FrozenEntityState, ...]


@dataclass(frozen=True, slots=True)
class FrozenArtifactState:
    artifact_id: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class FrozenNormalizedDocumentState:
    document_id: str
    sha256: str
    parser_name: str
    parser_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "document_id": self.document_id,
            "sha256": self.sha256,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
        }


@dataclass(frozen=True, slots=True)
class FrozenResearchBundle:
    """Typed application projection of one verified schema-v3 proof bundle."""

    bundle_sha256: str
    manifest_sha256: str
    document_id: str
    artifact: FrozenArtifactState
    normalized_document: FrozenNormalizedDocumentState
    claims: tuple[FrozenClaimState, ...]


@dataclass(frozen=True, slots=True)
class EntityFingerprintChange:
    entity_id: str
    before_sha256: str
    after_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.entity_id,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
        }


@dataclass(frozen=True, slots=True)
class EntityCollectionDiff:
    added: tuple[FrozenEntityState, ...]
    removed: tuple[FrozenEntityState, ...]
    changed: tuple[EntityFingerprintChange, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, object]:
        return {
            "added": [item.to_dict() for item in self.added],
            "removed": [item.to_dict() for item in self.removed],
            "changed": [item.to_dict() for item in self.changed],
        }


@dataclass(frozen=True, slots=True)
class ClaimDiff:
    claim_id: str
    change: str
    before_sha256: str | None
    after_sha256: str | None
    evidence: EntityCollectionDiff
    verifications: EntityCollectionDiff

    @property
    def has_changes(self) -> bool:
        return self.change != "unchanged" or self.evidence.has_changes or self.verifications.has_changes

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "change": self.change,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "evidence": self.evidence.to_dict(),
            "verifications": self.verifications.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FrozenResearchDiff:
    """Stable, transport-neutral diff between two frozen schema-v3 research bundles."""

    before_bundle_sha256: str
    after_bundle_sha256: str
    before_document_id: str
    after_document_id: str
    same_document: bool
    byte_identical: bool
    manifest_changed: bool
    artifact_changed: bool
    before_artifact: FrozenArtifactState
    after_artifact: FrozenArtifactState
    normalized_document_changed: bool
    before_normalized_document: FrozenNormalizedDocumentState
    after_normalized_document: FrozenNormalizedDocumentState
    claims: tuple[ClaimDiff, ...]

    @property
    def materially_equal(self) -> bool:
        return not (
            self.manifest_changed
            or self.artifact_changed
            or self.normalized_document_changed
            or any(claim.has_changes for claim in self.claims)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "before_bundle_sha256": self.before_bundle_sha256,
            "after_bundle_sha256": self.after_bundle_sha256,
            "before_document_id": self.before_document_id,
            "after_document_id": self.after_document_id,
            "same_document": self.same_document,
            "byte_identical": self.byte_identical,
            "materially_equal": self.materially_equal,
            "manifest_changed": self.manifest_changed,
            "artifact": {
                "changed": self.artifact_changed,
                "before": self.before_artifact.to_dict(),
                "after": self.after_artifact.to_dict(),
            },
            "normalized_document": {
                "changed": self.normalized_document_changed,
                "before": self.before_normalized_document.to_dict(),
                "after": self.after_normalized_document.to_dict(),
            },
            "claims": [claim.to_dict() for claim in self.claims],
        }


def diff_frozen_research(
    before: FrozenResearchBundle,
    after: FrozenResearchBundle,
) -> FrozenResearchDiff:
    """Compare two verified frozen states using only exact identities and canonical fingerprints."""
    before_claims = {item.claim.entity_id: item for item in before.claims}
    after_claims = {item.claim.entity_id: item for item in after.claims}
    claim_diffs = tuple(
        _diff_claim(before_claims.get(claim_id), after_claims.get(claim_id))
        for claim_id in sorted(before_claims.keys() | after_claims.keys())
    )
    return FrozenResearchDiff(
        before_bundle_sha256=before.bundle_sha256,
        after_bundle_sha256=after.bundle_sha256,
        before_document_id=before.document_id,
        after_document_id=after.document_id,
        same_document=before.document_id == after.document_id,
        byte_identical=before.bundle_sha256 == after.bundle_sha256,
        manifest_changed=before.manifest_sha256 != after.manifest_sha256,
        artifact_changed=before.artifact != after.artifact,
        before_artifact=before.artifact,
        after_artifact=after.artifact,
        normalized_document_changed=before.normalized_document != after.normalized_document,
        before_normalized_document=before.normalized_document,
        after_normalized_document=after.normalized_document,
        claims=claim_diffs,
    )


def _diff_claim(before: FrozenClaimState | None, after: FrozenClaimState | None) -> ClaimDiff:
    if before is None:
        assert after is not None
        change = "added"
        before_sha256 = None
        after_sha256 = after.claim.sha256
        evidence = _diff_entities((), after.evidence)
        verifications = _diff_entities((), after.verifications)
        claim_id = after.claim.entity_id
    elif after is None:
        change = "removed"
        before_sha256 = before.claim.sha256
        after_sha256 = None
        evidence = _diff_entities(before.evidence, ())
        verifications = _diff_entities(before.verifications, ())
        claim_id = before.claim.entity_id
    else:
        change = "changed" if before.claim.sha256 != after.claim.sha256 else "unchanged"
        before_sha256 = before.claim.sha256
        after_sha256 = after.claim.sha256
        evidence = _diff_entities(before.evidence, after.evidence)
        verifications = _diff_entities(before.verifications, after.verifications)
        claim_id = before.claim.entity_id
    return ClaimDiff(
        claim_id=claim_id,
        change=change,
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        evidence=evidence,
        verifications=verifications,
    )


def _diff_entities(
    before: tuple[FrozenEntityState, ...],
    after: tuple[FrozenEntityState, ...],
) -> EntityCollectionDiff:
    before_by_id = {item.entity_id: item for item in before}
    after_by_id = {item.entity_id: item for item in after}
    added_ids = sorted(after_by_id.keys() - before_by_id.keys())
    removed_ids = sorted(before_by_id.keys() - after_by_id.keys())
    shared_ids = sorted(before_by_id.keys() & after_by_id.keys())
    changed = tuple(
        EntityFingerprintChange(
            entity_id=entity_id,
            before_sha256=before_by_id[entity_id].sha256,
            after_sha256=after_by_id[entity_id].sha256,
        )
        for entity_id in shared_ids
        if before_by_id[entity_id].sha256 != after_by_id[entity_id].sha256
    )
    return EntityCollectionDiff(
        added=tuple(after_by_id[entity_id] for entity_id in added_ids),
        removed=tuple(before_by_id[entity_id] for entity_id in removed_ids),
        changed=changed,
    )
