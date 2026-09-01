from __future__ import annotations

from dataclasses import replace

import pytest

from tarkka.application.frozen_research_diff import (
    FrozenArtifactState,
    FrozenClaimState,
    FrozenEntityState,
    FrozenNormalizedDocumentState,
    FrozenResearchBundle,
    diff_frozen_research,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_DOCUMENT_A = "00000000-0000-0000-0000-00000000d001"
_DOCUMENT_B = "00000000-0000-0000-0000-00000000d002"
_CLAIM_A = "00000000-0000-0000-0000-00000000c001"
_CLAIM_B = "00000000-0000-0000-0000-00000000c002"
_EVIDENCE_A = "00000000-0000-0000-0000-00000000e001"
_EVIDENCE_B = "00000000-0000-0000-0000-00000000e002"
_EVIDENCE_C = "00000000-0000-0000-0000-00000000e003"
_RELATION_A = "00000000-0000-0000-0000-00000000a001"
_RELATION_B = "00000000-0000-0000-0000-00000000a002"
_ARTIFACT_A = "00000000-0000-0000-0000-00000000f001"
_ARTIFACT_B = "00000000-0000-0000-0000-00000000f002"


def _entity(entity_id: str, marker: str) -> FrozenEntityState:
    return FrozenEntityState(entity_id=entity_id, sha256=marker * 64)


def _claim(
    claim_id: str = _CLAIM_A,
    *,
    marker: str = "1",
    evidence: tuple[FrozenEntityState, ...] = (),
    verifications: tuple[FrozenEntityState, ...] = (),
) -> FrozenClaimState:
    return FrozenClaimState(
        claim=_entity(claim_id, marker),
        evidence=evidence,
        verifications=verifications,
    )


def _bundle(
    *,
    bundle_marker: str = "a",
    manifest_marker: str = "b",
    document_id: str = _DOCUMENT_A,
    artifact: FrozenArtifactState | None = None,
    normalized: FrozenNormalizedDocumentState | None = None,
    claims: tuple[FrozenClaimState, ...] = (),
) -> FrozenResearchBundle:
    return FrozenResearchBundle(
        bundle_sha256=bundle_marker * 64,
        manifest_sha256=manifest_marker * 64,
        document_id=document_id,
        artifact=artifact
        or FrozenArtifactState(
            artifact_id=_ARTIFACT_A,
            sha256="c" * 64,
            size_bytes=10,
        ),
        normalized_document=normalized
        or FrozenNormalizedDocumentState(
            document_id=document_id,
            sha256="d" * 64,
            parser_name="plain-text",
            parser_version="3",
        ),
        claims=claims,
    )


def test_identical_frozen_state_is_materially_equal_and_stably_serialized() -> None:
    claim = _claim(
        evidence=(_entity(_EVIDENCE_A, "2"),),
        verifications=(_entity(_RELATION_A, "3"),),
    )
    bundle = _bundle(claims=(claim,))

    result = diff_frozen_research(bundle, bundle)
    payload = result.to_dict()

    assert result.materially_equal is True
    assert result.byte_identical is True
    assert result.same_document is True
    assert result.claims[0].change == "unchanged"
    assert result.claims[0].has_changes is False
    assert result.claims[0].evidence.has_changes is False
    assert payload["materially_equal"] is True
    assert payload["artifact"] == {
        "changed": False,
        "before": bundle.artifact.to_dict(),
        "after": bundle.artifact.to_dict(),
    }
    assert payload["normalized_document"] == {
        "changed": False,
        "before": bundle.normalized_document.to_dict(),
        "after": bundle.normalized_document.to_dict(),
    }
    assert payload["claims"] == [result.claims[0].to_dict()]


def test_diff_reports_added_removed_and_changed_claim_children_deterministically() -> None:
    before_claim_a = _claim(
        marker="1",
        evidence=(
            _entity(_EVIDENCE_A, "1"),
            _entity(_EVIDENCE_B, "2"),
        ),
        verifications=(_entity(_RELATION_A, "3"),),
    )
    before_claim_b = _claim(
        _CLAIM_B,
        marker="4",
        evidence=(_entity(_EVIDENCE_C, "4"),),
    )
    after_claim_a = _claim(
        marker="9",
        evidence=(
            _entity(_EVIDENCE_A, "8"),
            _entity(_EVIDENCE_C, "7"),
        ),
        verifications=(
            _entity(_RELATION_A, "6"),
            _entity(_RELATION_B, "5"),
        ),
    )
    before = _bundle(claims=(before_claim_b, before_claim_a))
    after = _bundle(
        bundle_marker="e",
        manifest_marker="f",
        document_id=_DOCUMENT_B,
        artifact=FrozenArtifactState(
            artifact_id=_ARTIFACT_B,
            sha256="7" * 64,
            size_bytes=20,
        ),
        normalized=FrozenNormalizedDocumentState(
            document_id=_DOCUMENT_B,
            sha256="8" * 64,
            parser_name="semantic_html",
            parser_version="1",
        ),
        claims=(after_claim_a,),
    )

    result = diff_frozen_research(before, after)

    assert result.materially_equal is False
    assert result.byte_identical is False
    assert result.same_document is False
    assert result.manifest_changed is True
    assert result.artifact_changed is True
    assert result.normalized_document_changed is True
    assert [item.claim_id for item in result.claims] == [_CLAIM_A, _CLAIM_B]

    changed, removed = result.claims
    assert changed.change == "changed"
    assert changed.has_changes is True
    assert changed.evidence.added == (_entity(_EVIDENCE_C, "7"),)
    assert changed.evidence.removed == (_entity(_EVIDENCE_B, "2"),)
    assert changed.evidence.changed[0].to_dict() == {
        "id": _EVIDENCE_A,
        "before_sha256": "1" * 64,
        "after_sha256": "8" * 64,
    }
    assert changed.verifications.added == (_entity(_RELATION_B, "5"),)
    assert changed.verifications.changed[0].entity_id == _RELATION_A
    assert removed.change == "removed"
    assert removed.evidence.removed == (_entity(_EVIDENCE_C, "4"),)


def test_added_claim_projects_all_nested_entities_as_additions() -> None:
    added = _claim(
        evidence=(_entity(_EVIDENCE_B, "2"),),
        verifications=(_entity(_RELATION_B, "3"),),
    )

    result = diff_frozen_research(_bundle(), _bundle(bundle_marker="z", claims=(added,)))

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.change == "added"
    assert claim.before_sha256 is None
    assert claim.after_sha256 == added.claim.sha256
    assert claim.evidence.added == added.evidence
    assert claim.verifications.added == added.verifications


def test_manifest_only_difference_is_material() -> None:
    before = _bundle()
    after = replace(before, bundle_sha256="9" * 64, manifest_sha256="8" * 64)

    result = diff_frozen_research(before, after)

    assert result.manifest_changed is True
    assert result.artifact_changed is False
    assert result.normalized_document_changed is False
    assert result.materially_equal is False
