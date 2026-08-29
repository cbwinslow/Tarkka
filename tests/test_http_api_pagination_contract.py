from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.application.claim_lineage import (
    MAX_CLAIM_LINEAGE_OFFSET,
    MAX_CLAIM_LINEAGE_PAGE_SIZE,
)
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service
from tarkka.interfaces.http_api import create_app
from tests.support.claim_lineage import persist_local_claim_lineage


@pytest.mark.parametrize(
    "query_string",
    [
        b"offset=-1",
        b"evidence_offset=-1",
        f"offset={MAX_CLAIM_LINEAGE_OFFSET + 1}".encode(),
        f"evidence_offset={MAX_CLAIM_LINEAGE_OFFSET + 1}".encode(),
        f"limit={MAX_CLAIM_LINEAGE_PAGE_SIZE + 1}".encode(),
        f"evidence_limit={MAX_CLAIM_LINEAGE_PAGE_SIZE + 1}".encode(),
    ],
)
def test_http_delegates_pagination_invariants_to_the_application_service(
    tmp_path: Path,
    query_string: bytes,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    app = create_app(lineage=claim_lineage_service(home=tmp_path))

    status, response = app._dispatch(
        f"/v1/claims/{fixture.claim.extraction_id}/lineage",
        {"query_string": query_string},
    )

    assert status == 400
    assert response["error"]["code"] == "invalid_argument"


def test_zero_page_limits_are_intentional_and_suppress_expansion(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    app = create_app(lineage=claim_lineage_service(home=tmp_path))

    status, response = app._dispatch(
        f"/v1/claims/{fixture.claim.extraction_id}/lineage",
        {"query_string": b"limit=0&evidence_limit=0"},
    )

    assert status == 200
    lineage = response["lineage"]
    assert lineage["claim_evidence"] == []
    assert lineage["claim_evidence_page"] == {"offset": 0, "limit": 0, "total": 4}
    assert lineage["verification"]["assessments"] == []
    assert lineage["verification"]["limit"] == 0
