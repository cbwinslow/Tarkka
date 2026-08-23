from __future__ import annotations

import pytest

from tarkka.application.crawl_eligibility import (
    CrawlEligibilityReason,
    combine_crawl_eligibility,
)
from tarkka.domain.crawl_access import (
    CrawlAccessDecision,
    CrawlAccessReason,
    RobotsFetchOutcome,
)
from tarkka.domain.rights_access import (
    OperatorOverride,
    ResourceUse,
    RightsAccessDecision,
)

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_TARGET = "https://example.org/paper"
_ROBOTS = "https://example.org/robots.txt"


def _crawl(*, allowed: bool = True) -> CrawlAccessDecision:
    return CrawlAccessDecision(
        target_uri=_TARGET,
        robots_uri=_ROBOTS,
        product_token="TarkkaBot",
        allowed=allowed,
        reason=(CrawlAccessReason.ROBOTS_ALLOW if allowed else CrawlAccessReason.ROBOTS_DISALLOW),
        robots_outcome=RobotsFetchOutcome.SUCCESS,
        effective_min_request_interval_seconds=2.0,
    )


def _rights(
    *,
    retrieval: bool = True,
    storage: bool = True,
    analysis: bool = True,
    redistribution: bool = False,
    override: OperatorOverride = OperatorOverride.NONE,
    rationale: str | None = None,
) -> RightsAccessDecision:
    return RightsAccessDecision(
        target_uri=_TARGET,
        retrieval_allowed=retrieval,
        storage_allowed=storage,
        analysis_allowed=analysis,
        redistribution_allowed=redistribution,
        source_name="example-rights-policy",
        policy_reference="policy-v1",
        operator_override=override,
        rationale=rationale,
    )


def test_retrieval_permission_does_not_imply_redistribution_permission() -> None:
    rights = _rights(redistribution=False)
    decision = combine_crawl_eligibility(_crawl(), rights)

    assert decision.allowed is True
    assert decision.reason is CrawlEligibilityReason.ALLOWED
    assert rights.allows(ResourceUse.RETRIEVE) is True
    assert rights.allows(ResourceUse.STORE) is True
    assert rights.allows(ResourceUse.ANALYZE) is True
    assert rights.allows(ResourceUse.REDISTRIBUTE) is False


def test_rights_retrieval_denial_blocks_recursive_fetch() -> None:
    decision = combine_crawl_eligibility(_crawl(), _rights(retrieval=False))

    assert decision.allowed is False
    assert decision.reason is CrawlEligibilityReason.RIGHTS_RETRIEVAL_DENY


def test_operator_allow_override_cannot_override_robots_denial() -> None:
    rights = _rights(
        retrieval=True,
        override=OperatorOverride.ALLOW,
        rationale="explicitly reviewed source policy",
    )
    decision = combine_crawl_eligibility(_crawl(allowed=False), rights)

    assert decision.allowed is False
    assert decision.reason is CrawlEligibilityReason.ROBOTS_OR_TECHNICAL_DENY
    assert decision.rights.operator_override is OperatorOverride.ALLOW


def test_restrictive_operator_override_is_auditable() -> None:
    rights = _rights(
        retrieval=False,
        storage=False,
        analysis=False,
        redistribution=False,
        override=OperatorOverride.RESTRICT,
        rationale="domain owner requested no automated retrieval",
    )

    assert rights.operator_override is OperatorOverride.RESTRICT
    assert rights.rationale == "domain owner requested no automated retrieval"
    assert combine_crawl_eligibility(_crawl(), rights).allowed is False


def test_operator_override_requires_rationale() -> None:
    with pytest.raises(ValueError, match="auditable rationale"):
        _rights(override=OperatorOverride.ALLOW)


def test_authentication_and_paywall_are_recorded_without_implying_permission() -> None:
    rights = RightsAccessDecision(
        target_uri=_TARGET,
        retrieval_allowed=False,
        storage_allowed=False,
        analysis_allowed=False,
        redistribution_allowed=False,
        source_name="access-observation",
        requires_authentication=True,
        paywalled=True,
        rationale="resource requires an authenticated subscription",
    )

    assert rights.requires_authentication is True
    assert rights.paywalled is True
    assert rights.retrieval_allowed is False


def test_crawl_and_rights_decisions_must_refer_to_same_target() -> None:
    rights = RightsAccessDecision(
        target_uri="https://example.org/other",
        retrieval_allowed=True,
        storage_allowed=True,
        analysis_allowed=True,
        redistribution_allowed=False,
        source_name="policy",
    )

    with pytest.raises(ValueError, match="same target URI"):
        combine_crawl_eligibility(_crawl(), rights)
