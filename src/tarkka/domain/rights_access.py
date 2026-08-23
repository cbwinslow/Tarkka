from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tarkka.domain.http_observations import normalize_http_uri


class ResourceUse(StrEnum):
    """Distinct operations whose permission must not be inferred from one another."""

    RETRIEVE = "retrieve"
    STORE = "store"
    ANALYZE = "analyze"
    REDISTRIBUTE = "redistribute"


class OperatorOverride(StrEnum):
    """Whether an explicit operator rule changed the source-derived rights decision."""

    NONE = "none"
    RESTRICT = "restrict"
    ALLOW = "allow"


@dataclass(frozen=True, slots=True)
class RightsAccessDecision:
    """Provenance-friendly decision for resource use independent of transport/robots policy.

    These booleans are intentionally independent. Permission to retrieve a resource does not imply
    permission to store, analyze, or redistribute it, and a previously acquired resource may have
    local-use rights that differ from current network retrieval eligibility.
    """

    target_uri: str
    retrieval_allowed: bool
    storage_allowed: bool
    analysis_allowed: bool
    redistribution_allowed: bool
    source_name: str
    policy_reference: str | None = None
    requires_authentication: bool = False
    paywalled: bool = False
    operator_override: OperatorOverride = OperatorOverride.NONE
    rationale: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_uri",
            normalize_http_uri(self.target_uri, field_name="rights target URI"),
        )
        for field_name in (
            "retrieval_allowed",
            "storage_allowed",
            "analysis_allowed",
            "redistribution_allowed",
            "requires_authentication",
            "paywalled",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"rights {field_name} must be boolean")
        if not isinstance(self.source_name, str) or not self.source_name.strip():
            raise ValueError("rights source_name must be non-blank")
        object.__setattr__(self, "source_name", self.source_name.strip())
        if self.policy_reference is not None and (
            not isinstance(self.policy_reference, str) or not self.policy_reference.strip()
        ):
            raise ValueError("rights policy_reference must be non-blank when provided")
        if self.policy_reference is not None:
            object.__setattr__(self, "policy_reference", self.policy_reference.strip())
        if not isinstance(self.operator_override, OperatorOverride):
            raise ValueError("rights operator_override must be an OperatorOverride")
        if self.rationale is not None and (
            not isinstance(self.rationale, str) or not self.rationale.strip()
        ):
            raise ValueError("rights rationale must be non-blank when provided")
        if self.rationale is not None:
            object.__setattr__(self, "rationale", self.rationale.strip())
        if self.operator_override is not OperatorOverride.NONE and self.rationale is None:
            raise ValueError("operator rights overrides require an auditable rationale")

    def allows(self, use: ResourceUse) -> bool:
        """Return the explicit policy result for one resource use."""
        if not isinstance(use, ResourceUse):
            raise ValueError("resource use must be a ResourceUse")
        return {
            ResourceUse.RETRIEVE: self.retrieval_allowed,
            ResourceUse.STORE: self.storage_allowed,
            ResourceUse.ANALYZE: self.analysis_allowed,
            ResourceUse.REDISTRIBUTE: self.redistribution_allowed,
        }[use]
