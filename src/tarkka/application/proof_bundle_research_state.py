"""Pure application assembly for complete proof-bundle research-state snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from tarkka.application.claim_lineage import (
    MAX_CLAIM_EVIDENCE_PAGE_SIZE,
    MAX_CLAIM_LINEAGE_PAGE_SIZE,
    ClaimLineage,
    ClaimLineageService,
)
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.domain.extraction import Claim

PROOF_BUNDLE_RESEARCH_STATE_SCHEMA_VERSION = 1
MAX_PROOF_BUNDLE_CLAIMS = 10_000
MAX_PROOF_BUNDLE_EVIDENCE_PER_CLAIM = 10_000
MAX_PROOF_BUNDLE_RELATIONS_PER_CLAIM = 10_000


class ProofBundleResearchStateLimitError(ValueError):
    """Raised when complete auditable state exceeds an explicit export bound."""


class ProofBundleResearchStateSnapshotError(RuntimeError):
    """Raised when supposedly coherent lineage pages disagree about frozen state."""


@dataclass(frozen=True, slots=True)
class ProofBundleResearchStateLimits:
    """Hard bounds for complete Claim state included in one proof bundle."""

    max_claims: int = MAX_PROOF_BUNDLE_CLAIMS
    max_evidence_per_claim: int = MAX_PROOF_BUNDLE_EVIDENCE_PER_CLAIM
    max_relations_per_claim: int = MAX_PROOF_BUNDLE_RELATIONS_PER_CLAIM

    def __post_init__(self) -> None:
        if min(
            self.max_claims,
            self.max_evidence_per_claim,
            self.max_relations_per_claim,
        ) <= 0:
            raise ValueError("proof bundle research-state limits must be positive")


_DEFAULT_LIMITS = ProofBundleResearchStateLimits()


def collect_document_claim_lineages(
    document_id: UUID,
    claims: Sequence[Claim],
    service: ClaimLineageService,
    *,
    limits: ProofBundleResearchStateLimits = _DEFAULT_LIMITS,
) -> tuple[ClaimLineage, ...]:
    """Resolve every Claim completely under one caller-owned coherent snapshot."""
    if len(claims) > limits.max_claims:
        raise ProofBundleResearchStateLimitError(
            "proof bundle Claim count exceeds the configured maximum: "
            f"count={len(claims)}, maximum={limits.max_claims}"
        )
    ordered = sorted(claims, key=lambda item: str(item.extraction_id))
    claim_ids = [item.extraction_id for item in ordered]
    if len(claim_ids) != len(set(claim_ids)):
        raise ProofBundleResearchStateSnapshotError(
            "proof bundle research snapshot contains duplicate Claim identities"
        )
    if any(claim.document_id != document_id for claim in ordered):
        raise ProofBundleResearchStateSnapshotError(
            "proof bundle research snapshot contains a Claim from another Document"
        )
    return tuple(
        collect_complete_claim_lineage(service, claim.extraction_id, limits=limits)
        for claim in ordered
    )


def collect_complete_claim_lineage(
    service: ClaimLineageService,
    claim_id: UUID,
    *,
    limits: ProofBundleResearchStateLimits = _DEFAULT_LIMITS,
) -> ClaimLineage:
    """Collect complete original Evidence and assessments without silent truncation."""
    first = service.inspect(
        claim_id,
        offset=0,
        limit=MAX_CLAIM_LINEAGE_PAGE_SIZE,
        evidence_offset=0,
        evidence_limit=MAX_CLAIM_EVIDENCE_PAGE_SIZE,
    )
    if first.total_claim_evidence > limits.max_evidence_per_claim:
        raise ProofBundleResearchStateLimitError(
            "proof bundle Claim evidence count exceeds the configured maximum: "
            f"claim_id={claim_id}, count={first.total_claim_evidence}, "
            f"maximum={limits.max_evidence_per_claim}"
        )
    if first.total_relations > limits.max_relations_per_claim:
        raise ProofBundleResearchStateLimitError(
            "proof bundle verification relation count exceeds the configured maximum: "
            f"claim_id={claim_id}, count={first.total_relations}, "
            f"maximum={limits.max_relations_per_claim}"
        )

    evidence = list(first.claim_evidence)
    while len(evidence) < first.total_claim_evidence:
        page = service.inspect(
            claim_id,
            offset=0,
            limit=0,
            evidence_offset=len(evidence),
            evidence_limit=min(
                MAX_CLAIM_EVIDENCE_PAGE_SIZE,
                first.total_claim_evidence - len(evidence),
            ),
        )
        _require_same_lineage_snapshot(first, page)
        if not page.claim_evidence:
            raise ProofBundleResearchStateSnapshotError(
                "proof bundle Claim evidence pagination made no progress"
            )
        evidence.extend(page.claim_evidence)

    assessments = list(first.assessments)
    while len(assessments) < first.total_relations:
        page = service.inspect(
            claim_id,
            offset=len(assessments),
            limit=min(
                MAX_CLAIM_LINEAGE_PAGE_SIZE,
                first.total_relations - len(assessments),
            ),
            evidence_offset=0,
            evidence_limit=0,
        )
        _require_same_lineage_snapshot(first, page)
        if not page.assessments:
            raise ProofBundleResearchStateSnapshotError(
                "proof bundle verification pagination made no progress"
            )
        assessments.extend(page.assessments)

    if len(evidence) != first.total_claim_evidence or len(assessments) != first.total_relations:
        raise ProofBundleResearchStateSnapshotError(
            "proof bundle Claim lineage collection did not resolve exact totals"
        )
    return replace(
        first,
        claim_evidence=tuple(evidence),
        assessments=tuple(assessments),
    )


def document_research_state_view(
    document_id: UUID,
    lineages: Sequence[ClaimLineage],
    *,
    limits: ProofBundleResearchStateLimits = _DEFAULT_LIMITS,
) -> dict[str, object]:
    """Return the complete versioned research-state object embedded in bundle v2."""
    if len(lineages) > limits.max_claims:
        raise ProofBundleResearchStateLimitError(
            "proof bundle Claim count exceeds the configured maximum: "
            f"count={len(lineages)}, maximum={limits.max_claims}"
        )
    ordered = sorted(lineages, key=lambda item: str(item.claim.extraction_id))
    claim_ids = [item.claim.extraction_id for item in ordered]
    if len(claim_ids) != len(set(claim_ids)):
        raise ProofBundleResearchStateSnapshotError(
            "proof bundle research state contains duplicate Claim identities"
        )
    for lineage in ordered:
        if lineage.claim.document_id != document_id:
            raise ProofBundleResearchStateSnapshotError(
                "proof bundle research state contains a Claim from another Document"
            )
        if len(lineage.claim_evidence) != lineage.total_claim_evidence:
            raise ProofBundleResearchStateSnapshotError(
                "proof bundle research state contains incomplete Claim evidence"
            )
        if len(lineage.assessments) != lineage.total_relations:
            raise ProofBundleResearchStateSnapshotError(
                "proof bundle research state contains incomplete verification assessments"
            )
        if lineage.total_claim_evidence > limits.max_evidence_per_claim:
            raise ProofBundleResearchStateLimitError(
                "proof bundle Claim evidence count exceeds the configured maximum"
            )
        if lineage.total_relations > limits.max_relations_per_claim:
            raise ProofBundleResearchStateLimitError(
                "proof bundle verification relation count exceeds the configured maximum"
            )

    return {
        "schema_version": PROOF_BUNDLE_RESEARCH_STATE_SCHEMA_VERSION,
        "document_id": str(document_id),
        "claims": [
            claim_lineage_view(
                lineage,
                offset=0,
                limit=lineage.total_relations,
                evidence_offset=0,
                evidence_limit=lineage.total_claim_evidence,
            )
            for lineage in ordered
        ],
    }


def _require_same_lineage_snapshot(first: ClaimLineage, page: ClaimLineage) -> None:
    if (
        page.claim != first.claim
        or page.claim_run != first.claim_run
        or page.claim_source != first.claim_source
        or page.total_claim_evidence != first.total_claim_evidence
        or page.total_relations != first.total_relations
    ):
        raise ProofBundleResearchStateSnapshotError(
            "proof bundle Claim lineage changed while collecting a coherent snapshot"
        )
