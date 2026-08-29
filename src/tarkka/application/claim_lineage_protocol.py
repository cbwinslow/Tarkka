"""Bounded, transport-neutral agent response helpers for Claim lineage."""

from __future__ import annotations

import json
from uuid import UUID

from tarkka.application.claim_lineage import (
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineageService,
)
from tarkka.application.claim_lineage_contract import claim_lineage_problem
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.application.document_context_packages import MAX_CONTEXT_PACKAGE_ESTIMATED_TOKENS
from tarkka.domain.manifest import estimate_tokens

MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS = MAX_CONTEXT_PACKAGE_ESTIMATED_TOKENS


def agent_error(
    code: str,
    message: str,
    *,
    next_actions: tuple[str, ...] = (),
) -> dict[str, object]:
    """Return the stable machine-readable error envelope shared by agent transports."""
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "next_actions": list(next_actions),
        },
    }


def claim_lineage_response(
    service: ClaimLineageService,
    claim_id: UUID,
    *,
    offset: int = 0,
    limit: int = 20,
    evidence_offset: int = 0,
    evidence_limit: int = 20,
    max_estimated_tokens: int = MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
) -> dict[str, object]:
    """Resolve one bounded Claim-lineage request into the shared agent response envelope."""
    try:
        lineage = service.inspect(
            claim_id,
            offset=offset,
            limit=limit,
            evidence_offset=evidence_offset,
            evidence_limit=evidence_limit,
        )
    except (
        ClaimLineageArtifactNotFoundError,
        ClaimLineageCitationContextNotFoundError,
        ClaimLineageCitationRepositoryUnavailableError,
        ClaimLineageClaimNotFoundError,
        ClaimLineageDocumentNotFoundError,
        ClaimLineageEvidenceNotFoundError,
        ClaimLineageExtractionRunNotFoundError,
        ClaimLineageMismatchError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        problem = claim_lineage_problem(exc)
        return agent_error(problem.code, problem.message, next_actions=problem.next_actions)

    payload = claim_lineage_view(
        lineage,
        offset=offset,
        limit=limit,
        evidence_offset=evidence_offset,
        evidence_limit=evidence_limit,
    )
    estimated_tokens = estimate_tokens(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
    if estimated_tokens > max_estimated_tokens:
        return agent_error(
            "content_too_large",
            "claim lineage exceeds the configured estimated-token maximum; retry with a "
            "smaller evidence_limit and/or verification limit",
            next_actions=("claim_lineage",),
        )
    return {
        "ok": True,
        "lineage": payload,
        "estimated_tokens": estimated_tokens,
    }
