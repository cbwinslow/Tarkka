"""Stable machine-readable error vocabulary for Claim lineage transports."""

from __future__ import annotations

from dataclasses import dataclass

from tarkka.application.claim_lineage import (
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
)


@dataclass(frozen=True, slots=True)
class ClaimLineageProblem:
    """Transport-neutral machine problem produced for an expected lineage failure."""

    code: str
    message: str
    next_actions: tuple[str, ...] = ()


def claim_lineage_problem(exc: Exception) -> ClaimLineageProblem:
    """Map expected lineage/application/runtime failures to stable machine codes."""
    if isinstance(exc, ClaimLineageClaimNotFoundError):
        return ClaimLineageProblem(
            "claim_not_found",
            str(exc),
            ("research_capabilities",),
        )
    if isinstance(exc, ClaimLineageEvidenceNotFoundError):
        return ClaimLineageProblem("evidence_not_found", str(exc))
    if isinstance(exc, ClaimLineageExtractionRunNotFoundError):
        return ClaimLineageProblem("extraction_run_not_found", str(exc))
    if isinstance(exc, ClaimLineageDocumentNotFoundError):
        return ClaimLineageProblem("document_not_found", str(exc))
    if isinstance(exc, ClaimLineageArtifactNotFoundError):
        return ClaimLineageProblem("artifact_not_found", str(exc))
    if isinstance(exc, ClaimLineageCitationRepositoryUnavailableError):
        return ClaimLineageProblem("citation_repository_unavailable", str(exc))
    if isinstance(exc, ClaimLineageCitationContextNotFoundError):
        return ClaimLineageProblem("citation_context_not_found", str(exc))
    if isinstance(exc, ClaimLineageMismatchError):
        return ClaimLineageProblem("lineage_mismatch", str(exc))
    if isinstance(exc, ValueError):
        return ClaimLineageProblem(
            "invalid_argument",
            str(exc),
            ("research_operation_schema",),
        )
    if isinstance(exc, (OSError, RuntimeError)):
        return ClaimLineageProblem("backend_unavailable", str(exc))
    raise TypeError(f"unsupported Claim lineage error: {type(exc).__name__}")
