"""Deterministic, bounded research-state assembly for one normalized Document."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from tarkka.application.claim_lineage import (
    MAX_CLAIM_EVIDENCE_OFFSET,
    MAX_CLAIM_EVIDENCE_PAGE_SIZE,
    MAX_CLAIM_LINEAGE_OFFSET,
    MAX_CLAIM_LINEAGE_PAGE_SIZE,
    ClaimLineage,
)
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.domain.extraction import Claim

DOCUMENT_RESEARCH_STATE_FORMAT = "tarkka.document-research-state"
DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION = 1
MAX_DOCUMENT_RESEARCH_STATE_CLAIMS = 10_000
MAX_DOCUMENT_RESEARCH_STATE_CLAIM_EVIDENCE = (
    MAX_CLAIM_EVIDENCE_OFFSET + MAX_CLAIM_EVIDENCE_PAGE_SIZE
)
MAX_DOCUMENT_RESEARCH_STATE_RELATIONS = MAX_CLAIM_LINEAGE_OFFSET + MAX_CLAIM_LINEAGE_PAGE_SIZE


class ClaimLineageInspector(Protocol):
    """Minimal read contract needed to assemble complete document research state."""

    def inspect(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        evidence_offset: int = 0,
        evidence_limit: int = 20,
    ) -> ClaimLineage: ...


class DocumentResearchStateLimitError(ValueError):
    """Raised when a complete auditable export would exceed configured resource limits."""


class DocumentResearchStateMismatchError(ValueError):
    """Raised when paged Claim lineage disagrees with the frozen Document snapshot."""


@dataclass(frozen=True, slots=True)
class DocumentResearchStateLimits:
    """Explicit fail-closed ceilings for one Document research-state export."""

    max_claims: int = 1_000
    max_claim_evidence_per_claim: int = 1_000
    max_relations_per_claim: int = 1_000

    def __post_init__(self) -> None:
        values = (
            ("max_claims", self.max_claims, MAX_DOCUMENT_RESEARCH_STATE_CLAIMS),
            (
                "max_claim_evidence_per_claim",
                self.max_claim_evidence_per_claim,
                MAX_DOCUMENT_RESEARCH_STATE_CLAIM_EVIDENCE,
            ),
            (
                "max_relations_per_claim",
                self.max_relations_per_claim,
                MAX_DOCUMENT_RESEARCH_STATE_RELATIONS,
            ),
        )
        for name, value, supported_maximum in values:
            if value < 0:
                raise ValueError(f"document research-state {name} must be non-negative")
            if value > supported_maximum:
                raise ValueError(
                    f"document research-state {name} exceeds the supported maximum: "
                    f"{supported_maximum}"
                )


DEFAULT_DOCUMENT_RESEARCH_STATE_LIMITS = DocumentResearchStateLimits()


@dataclass(frozen=True, slots=True)
class DocumentResearchState:
    """Complete validated Claim lineage frozen for one normalized Document."""

    document_id: UUID
    claim_lineages: tuple[ClaimLineage, ...]


def assemble_document_research_state(
    document_id: UUID,
    claims: tuple[Claim, ...],
    service: ClaimLineageInspector,
    *,
    limits: DocumentResearchStateLimits = DEFAULT_DOCUMENT_RESEARCH_STATE_LIMITS,
) -> DocumentResearchState:
    """Collect complete Claim/evidence/verification lineage without silent truncation."""
    ordered_claims = tuple(sorted(claims, key=lambda item: str(item.extraction_id)))
    if len(ordered_claims) > limits.max_claims:
        raise DocumentResearchStateLimitError(
            "document research-state Claim count exceeds the configured maximum: "
            f"count={len(ordered_claims)}, maximum={limits.max_claims}"
        )
    for claim in ordered_claims:
        if claim.document_id != document_id:
            raise DocumentResearchStateMismatchError(
                "document research-state Claim belongs to a different Document"
            )

    return DocumentResearchState(
        document_id=document_id,
        claim_lineages=tuple(
            _collect_complete_claim_lineage(claim, service, limits=limits)
            for claim in ordered_claims
        ),
    )


def document_research_state_view(state: DocumentResearchState) -> dict[str, object]:
    """Return the versioned canonical JSON-compatible view persisted by proof bundle v2."""
    return {
        "format": DOCUMENT_RESEARCH_STATE_FORMAT,
        "schema_version": DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION,
        "document_id": str(state.document_id),
        "claims": [
            claim_lineage_view(
                lineage,
                offset=0,
                limit=lineage.total_relations,
                evidence_offset=0,
                evidence_limit=lineage.total_claim_evidence,
            )
            for lineage in state.claim_lineages
        ],
    }


def _collect_complete_claim_lineage(
    claim: Claim,
    service: ClaimLineageInspector,
    *,
    limits: DocumentResearchStateLimits,
) -> ClaimLineage:
    relation_page_size = min(MAX_CLAIM_LINEAGE_PAGE_SIZE, limits.max_relations_per_claim)
    evidence_page_size = min(
        MAX_CLAIM_EVIDENCE_PAGE_SIZE,
        limits.max_claim_evidence_per_claim,
    )
    first = service.inspect(
        claim.extraction_id,
        offset=0,
        limit=relation_page_size,
        evidence_offset=0,
        evidence_limit=evidence_page_size,
    )
    if first.claim != claim:
        raise DocumentResearchStateMismatchError(
            "document research-state Claim listing disagrees with lineage lookup"
        )
    if first.total_claim_evidence > limits.max_claim_evidence_per_claim:
        raise DocumentResearchStateLimitError(
            "document research-state Claim evidence exceeds the configured maximum: "
            f"claim_id={claim.extraction_id}, count={first.total_claim_evidence}, "
            f"maximum={limits.max_claim_evidence_per_claim}"
        )
    if first.total_relations > limits.max_relations_per_claim:
        raise DocumentResearchStateLimitError(
            "document research-state verification relations exceed the configured maximum: "
            f"claim_id={claim.extraction_id}, count={first.total_relations}, "
            f"maximum={limits.max_relations_per_claim}"
        )

    evidence = list(first.claim_evidence)
    for evidence_offset in range(
        evidence_page_size,
        first.total_claim_evidence,
        MAX_CLAIM_EVIDENCE_PAGE_SIZE,
    ):
        page = service.inspect(
            claim.extraction_id,
            offset=0,
            limit=0,
            evidence_offset=evidence_offset,
            evidence_limit=min(
                MAX_CLAIM_EVIDENCE_PAGE_SIZE,
                first.total_claim_evidence - evidence_offset,
            ),
        )
        evidence.extend(page.claim_evidence)

    assessments = list(first.assessments)
    for offset in range(
        relation_page_size,
        first.total_relations,
        MAX_CLAIM_LINEAGE_PAGE_SIZE,
    ):
        page = service.inspect(
            claim.extraction_id,
            offset=offset,
            limit=min(MAX_CLAIM_LINEAGE_PAGE_SIZE, first.total_relations - offset),
            evidence_offset=0,
            evidence_limit=0,
        )
        assessments.extend(page.assessments)

    evidence_ids = tuple(item.evidence.evidence_id for item in evidence)
    if evidence_ids != claim.evidence_ids:
        raise DocumentResearchStateMismatchError(
            "complete Claim evidence pages do not match the Claim evidence identities"
        )
    relation_ids = tuple(item.relation.relation_id for item in assessments)
    if len(relation_ids) != len(set(relation_ids)):
        raise DocumentResearchStateMismatchError(
            "complete Claim verification pages contain duplicate relation identities"
        )
    if len(assessments) != first.total_relations:
        raise DocumentResearchStateMismatchError(
            "complete Claim verification pages do not match the reported relation count"
        )

    return ClaimLineage(
        claim=first.claim,
        claim_run=first.claim_run,
        claim_source=first.claim_source,
        total_claim_evidence=first.total_claim_evidence,
        claim_evidence=tuple(evidence),
        total_relations=first.total_relations,
        assessments=tuple(sorted(assessments, key=lambda item: str(item.relation.relation_id))),
    )
