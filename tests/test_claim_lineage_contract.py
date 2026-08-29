from __future__ import annotations

import pytest

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
from tarkka.application.claim_lineage_contract import claim_lineage_problem

pytestmark = [pytest.mark.unit, pytest.mark.contract]


@pytest.mark.parametrize(
    ("error", "code", "next_actions"),
    [
        (
            ClaimLineageClaimNotFoundError("missing claim"),
            "claim_not_found",
            ("research_capabilities",),
        ),
        (ClaimLineageEvidenceNotFoundError("missing evidence"), "evidence_not_found", ()),
        (
            ClaimLineageExtractionRunNotFoundError("missing run"),
            "extraction_run_not_found",
            (),
        ),
        (ClaimLineageDocumentNotFoundError("missing document"), "document_not_found", ()),
        (ClaimLineageArtifactNotFoundError("missing artifact"), "artifact_not_found", ()),
        (
            ClaimLineageCitationRepositoryUnavailableError("no citations"),
            "citation_repository_unavailable",
            (),
        ),
        (
            ClaimLineageCitationContextNotFoundError("missing context"),
            "citation_context_not_found",
            (),
        ),
        (ClaimLineageMismatchError("mismatch"), "lineage_mismatch", ()),
        (ValueError("bad page"), "invalid_argument", ("research_operation_schema",)),
        (OSError("disk unavailable"), "backend_unavailable", ()),
        (RuntimeError("backend unavailable"), "backend_unavailable", ()),
    ],
)
def test_claim_lineage_problem_maps_expected_failures(
    error: Exception,
    code: str,
    next_actions: tuple[str, ...],
) -> None:
    problem = claim_lineage_problem(error)

    assert problem.code == code
    assert problem.message == str(error)
    assert problem.next_actions == next_actions


def test_claim_lineage_problem_rejects_unexpected_programming_errors() -> None:
    with pytest.raises(TypeError, match="unsupported Claim lineage error: TypeError"):
        claim_lineage_problem(TypeError("programming bug"))
