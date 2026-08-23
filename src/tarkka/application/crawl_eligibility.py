from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tarkka.domain.crawl_access import CrawlAccessDecision
from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.rights_access import RightsAccessDecision


class CrawlEligibilityReason(StrEnum):
    """Stable final reasons after composing crawl and rights policy."""

    ALLOWED = "allowed"
    ROBOTS_OR_TECHNICAL_DENY = "robots_or_technical_deny"
    RIGHTS_RETRIEVAL_DENY = "rights_retrieval_deny"


@dataclass(frozen=True, slots=True)
class CrawlEligibilityDecision:
    """Final recursive-fetch eligibility without collapsing independent policy evidence."""

    target_uri: str
    allowed: bool
    reason: CrawlEligibilityReason
    crawl: CrawlAccessDecision
    rights: RightsAccessDecision

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_uri",
            normalize_http_uri(self.target_uri, field_name="crawl eligibility target URI"),
        )
        if not isinstance(self.allowed, bool):
            raise ValueError("crawl eligibility allowed must be boolean")
        if not isinstance(self.reason, CrawlEligibilityReason):
            raise ValueError("crawl eligibility reason must be a CrawlEligibilityReason")
        if not isinstance(self.crawl, CrawlAccessDecision):
            raise ValueError("crawl eligibility crawl decision must be a CrawlAccessDecision")
        if not isinstance(self.rights, RightsAccessDecision):
            raise ValueError("crawl eligibility rights decision must be a RightsAccessDecision")
        if self.crawl.target_uri != self.target_uri or self.rights.target_uri != self.target_uri:
            raise ValueError("crawl and rights decisions must refer to the same target URI")



def combine_crawl_eligibility(
    crawl: CrawlAccessDecision,
    rights: RightsAccessDecision,
) -> CrawlEligibilityDecision:
    """Compose recursive-fetch eligibility without allowing rights overrides to weaken safety.

    A restrictive technical/robots decision always wins. Operator/source rights policy is then
    consulted only for retrieval eligibility. Storage, analysis, and redistribution remain
    independent downstream decisions and are not inferred from permission to fetch.
    """
    if not isinstance(crawl, CrawlAccessDecision):
        raise ValueError("crawl decision must be a CrawlAccessDecision")
    if not isinstance(rights, RightsAccessDecision):
        raise ValueError("rights decision must be a RightsAccessDecision")
    if crawl.target_uri != rights.target_uri:
        raise ValueError("crawl and rights decisions must refer to the same target URI")

    if not crawl.allowed:
        reason = CrawlEligibilityReason.ROBOTS_OR_TECHNICAL_DENY
        allowed = False
    elif not rights.retrieval_allowed:
        reason = CrawlEligibilityReason.RIGHTS_RETRIEVAL_DENY
        allowed = False
    else:
        reason = CrawlEligibilityReason.ALLOWED
        allowed = True

    return CrawlEligibilityDecision(
        target_uri=crawl.target_uri,
        allowed=allowed,
        reason=reason,
        crawl=crawl,
        rights=rights,
    )
