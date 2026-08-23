from __future__ import annotations

import pytest

from tarkka.application.crawl_eligibility import (
    CrawlEligibilityDecision,
    CrawlEligibilityReason,
)
from tarkka.domain.crawl_access import (
    CrawlAccessDecision,
    CrawlAccessReason,
    RobotsFetchOutcome,
)
from tarkka.domain.rights_access import RightsAccessDecision

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_TARGET = "https://example.org/paper"


def _crawl(*, allowed: bool) -> CrawlAccessDecision:
    return CrawlAccessDecision(
        target_uri=_TARGET,
        robots_uri="https://example.org/robots.txt",
        product_token="TarkkaBot",
        allowed=allowed,
        reason=(CrawlAccessReason.ROBOTS_ALLOW if allowed else CrawlAccessReason.ROBOTS_DISALLOW),
        robots_outcome=RobotsFetchOutcome.SUCCESS,
        effective_min_request_interval_seconds=0.0,
    )


def _rights(*, retrieval: bool) -> RightsAccessDecision:
    return RightsAccessDecision(
        target_uri=_TARGET,
        retrieval_allowed=retrieval,
        storage_allowed=False,
        analysis_allowed=False,
        redistribution_allowed=False,
        source_name="test-policy",
    )


@pytest.mark.parametrize(
    ("allowed", "reason", "crawl_allowed", "retrieval_allowed"),
    [
        (True, CrawlEligibilityReason.ALLOWED, False, True),
        (True, CrawlEligibilityReason.ALLOWED, True, False),
        (False, CrawlEligibilityReason.RIGHTS_RETRIEVAL_DENY, False, False),
        (False, CrawlEligibilityReason.ROBOTS_OR_TECHNICAL_DENY, True, False),
    ],
)
def test_direct_construction_rejects_inconsistent_policy_evidence(
    allowed: bool,
    reason: CrawlEligibilityReason,
    crawl_allowed: bool,
    retrieval_allowed: bool,
) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        CrawlEligibilityDecision(
            target_uri=_TARGET,
            allowed=allowed,
            reason=reason,
            crawl=_crawl(allowed=crawl_allowed),
            rights=_rights(retrieval=retrieval_allowed),
        )
