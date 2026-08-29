from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import (
    ClaimLineageClaimNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineagePaginationError,
    ClaimLineageService,
)
from tarkka.application.claim_lineage_protocol import agent_error, claim_lineage_response
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service
from tests.support.claim_lineage import persist_local_claim_lineage


class _RaisingLineageService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def inspect(self, *_args: object, **_kwargs: object) -> object:
        raise self._error


def test_agent_error_is_stable_and_transport_neutral() -> None:
    assert agent_error("invalid_argument", "bad input", next_actions=("retry",)) == {
        "ok": False,
        "error": {
            "code": "invalid_argument",
            "message": "bad input",
            "next_actions": ["retry"],
        },
    }


def test_claim_lineage_response_matches_the_shared_view(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    service = claim_lineage_service(home=tmp_path)

    response = claim_lineage_response(
        service,
        fixture.claim.extraction_id,
        offset=0,
        limit=1,
        evidence_offset=1,
        evidence_limit=2,
    )
    expected = claim_lineage_view(
        service.inspect(
            fixture.claim.extraction_id,
            offset=0,
            limit=1,
            evidence_offset=1,
            evidence_limit=2,
        ),
        offset=0,
        limit=1,
        evidence_offset=1,
        evidence_limit=2,
    )

    assert response["ok"] is True
    assert response["lineage"] == expected
    assert response["estimated_tokens"] > 0


def test_claim_lineage_response_fails_closed_when_the_bounded_view_is_still_too_large(
    tmp_path: Path,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)

    response = claim_lineage_response(
        claim_lineage_service(home=tmp_path),
        fixture.claim.extraction_id,
        max_estimated_tokens=0,
    )

    assert response == {
        "ok": False,
        "error": {
            "code": "content_too_large",
            "message": (
                "claim lineage exceeds the configured estimated-token maximum; retry with a "
                "smaller evidence_limit and/or verification limit"
            ),
            "next_actions": ["claim_lineage"],
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ClaimLineageClaimNotFoundError("missing claim"), "claim_not_found"),
        (ClaimLineageMismatchError("identity mismatch"), "lineage_mismatch"),
        (ClaimLineagePaginationError("bad page"), "invalid_argument"),
        (ValueError("corrupt persisted value"), "backend_unavailable"),
        (OSError("backend unavailable"), "backend_unavailable"),
        (RuntimeError("backend unavailable"), "backend_unavailable"),
    ],
)
def test_claim_lineage_response_preserves_machine_problem_classification(
    error: Exception,
    expected_code: str,
) -> None:
    service = cast(ClaimLineageService, _RaisingLineageService(error))

    response = claim_lineage_response(service, UUID(int=1))

    assert response["ok"] is False
    assert response["error"]["code"] == expected_code
